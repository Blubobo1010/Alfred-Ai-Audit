// Install a downloaded macOS update without Squirrel.Mac. Squirrel reads the
// whole update zip into memory and crashes once it passes 1 GiB, so
// electron-updater only checks and downloads here. This module unpacks the zip
// next to the user's data, checks it against the running app's designated
// requirement, and hands the swap to the app's own signed binary running as
// Node once this process has quit. App Management lets a binary of the same
// team replace the bundle, and the helper only renames the bundle as a whole:
// nothing ever writes inside the installed app.

import { type ChildProcess, spawn as nodeSpawn } from 'node:child_process'
import * as fs from 'node:fs'
import * as path from 'node:path'

import { canonicalChannelPath, type NativeCommandResult, runChannelCommand } from './channel-native'
import { type RelaunchWaiterHandle, waiterLogTail } from './relaunch-waiter'

export const MAC_STAGING_PREFIX = 'mac-update-'
export const SWAP_LOG_FILENAME = 'update-swap.log'
export const SWAP_SCRIPT_FILENAME = 'swap.cjs'

const GIB = 1024 * 1024 * 1024
const UNPACK_TIMEOUT_MS = 20 * 60_000
const VERIFY_TIMEOUT_MS = 20 * 60_000
const DEFAULT_HANDSHAKE_MS = 15_000
const DEFAULT_WAIT_TIMEOUT_MS = 15 * 60_000

export type SpawnSwapHelper = (
  command: string,
  args: string[],
  options: { cwd: string; detached: boolean; env: NodeJS.ProcessEnv; stdio: 'ignore' }
) => ChildProcess

export interface MacBundleInstallerDeps {
  /** The running executable (process.execPath): Contents/MacOS/<name> of the installed bundle. */
  execPath: string
  /** Where updates are unpacked; must be on the app's volume so the swap is a rename. */
  stagingRoot: () => string
  /** The helper's log, shared by every attempt (each line carries its staging dir name). */
  logFile: () => string
  productName: string
  releasesUrl: string
  log: (message: string) => void
  emitProgress: (progress: { stage: string; message: string; percent: number | null }) => void
  run?: (file: string, args: readonly string[], timeout?: number) => Promise<NativeCommandResult>
  spawn?: SpawnSwapHelper
  freeBytes?: (dir: string) => number
  /** The requirement the new bundle must satisfy; defaults to the running app's own. */
  requirement?: (appPath: string) => Promise<string>
  relaunchCommand?: (appPath: string) => string[]
  /** Prints a process's start time when given its pid as the last argument. */
  psCommand?: string[]
  pid?: number
  env?: NodeJS.ProcessEnv
  handshakeMs?: number
  waitTimeoutMs?: number
}

export interface MacBundleInstaller {
  /** Refuses, before anything is downloaded, an install this copy cannot finish. */
  preflight: () => Promise<void>
  /** Unpacks and verifies the downloaded zip; nothing is stopped yet. */
  stage: (files: string[], version: string) => Promise<void>
  /** Starts the helper, which waits for this process to exit before it swaps. */
  startSwap: () => Promise<RelaunchWaiterHandle>
  /** Throws unless the helper is still waiting: quitting without it installs nothing. */
  assertSwapRunning: () => void
}

interface StagedUpdate {
  appPath: string
  stagedApp: string
  dir: string
  zip: string
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

function freeBytesOn(dir: string): number {
  const stats = fs.statfsSync(dir)

  return stats.bavail * stats.bsize
}

function gib(bytes: number): string {
  return (bytes / GIB).toFixed(1)
}

export function createMacBundleInstaller(deps: MacBundleInstallerDeps): MacBundleInstaller {
  const run = deps.run ?? runChannelCommand
  const spawn = deps.spawn ?? (nodeSpawn as unknown as SpawnSwapHelper)
  const freeBytes = deps.freeBytes ?? freeBytesOn
  const handshakeMs = deps.handshakeMs ?? DEFAULT_HANDSHAKE_MS
  let staged: StagedUpdate | undefined
  let helper: ChildProcess | undefined

  const dmgError = (reason: string): Error =>
    new Error(
      `${deps.productName} cannot update itself here: ${reason}. Install the update from the DMG: ${deps.releasesUrl}`
    )

  // Electron's fs shows app.asar as a folder, so a recursive delete of a bundle
  // fails unless asar support is off for the call.
  const removeTree = (target: string): void => {
    const proc = process as { noAsar?: boolean }
    const asar = proc.noAsar
    proc.noAsar = true

    try {
      fs.rmSync(target, { recursive: true, force: true })
    } catch (error) {
      deps.log(`[updates] macOS update: could not remove ${target}: ${errorText(error)}`)
    } finally {
      proc.noAsar = asar
    }
  }

  const runningAppPath = async (): Promise<string> => {
    const executable = await canonicalChannelPath(deps.execPath)
    const appPath = path.resolve(executable, '../../..')

    if (!appPath.endsWith('.app') || path.basename(path.dirname(executable)) !== 'MacOS') {
      throw dmgError(`${appPath} is not an app bundle`)
    }

    return appPath
  }

  const designatedRequirement = async (appPath: string): Promise<string> => {
    let output: NativeCommandResult

    try {
      output = await run('/usr/bin/codesign', ['-d', '-r-', appPath])
    } catch (error) {
      deps.log(`[updates] macOS update: cannot read the app's signature: ${errorText(error)}`)

      throw dmgError('this copy is not signed with a Developer ID')
    }

    // codesign prints the requirement on stdout or stderr depending on the terminal.
    const requirement = /^designated => (.+)$/m.exec(`${output.stdout}\n${output.stderr}`)?.[1]?.trim() ?? ''

    if (!requirement.includes('anchor apple generic') || !/certificate leaf\[subject\.OU\]/.test(requirement)) {
      throw dmgError('this copy is not signed with a Developer ID')
    }

    return requirement
  }

  const unpackedBytes = async (zip: string): Promise<number> => {
    try {
      const { stdout } = await run('/usr/bin/zipinfo', ['-t', zip])
      const bytes = Number(/(\d+) bytes uncompressed/.exec(stdout)?.[1])

      if (Number.isFinite(bytes) && bytes > 0) {
        return bytes
      }
    } catch (error) {
      deps.log(`[updates] macOS update: zipinfo failed, estimating the unpacked size: ${errorText(error)}`)
    }

    return fs.statSync(zip).size * 3
  }

  const progress = (message: string): void => {
    deps.emitProgress({ stage: 'prepare', message, percent: null })
  }

  const preflight = async (): Promise<void> => {
    const appPath = await runningAppPath()

    if (appPath.includes('/AppTranslocation/')) {
      throw dmgError('macOS is running it from a temporary read-only copy (move it to Applications first)')
    }

    // Moving a folder to another parent needs write access to the folder itself.
    for (const dir of [path.dirname(appPath), appPath]) {
      try {
        fs.accessSync(dir, fs.constants.W_OK)
      } catch {
        throw dmgError(`${dir} is not writable by this user`)
      }
    }

    if (fs.existsSync(`${appPath}.old`)) {
      deps.log(`[updates] macOS update: removing ${appPath}.old left by an earlier update`)
      removeTree(`${appPath}.old`)
    }
  }

  const stage = async (files: string[], version: string): Promise<void> => {
    staged = undefined

    if (files.length !== 1 || !files[0].endsWith('.zip')) {
      throw new Error('Expected exactly one macOS update zip')
    }

    if (!version) {
      throw new Error('The macOS feed did not name the update version')
    }

    const zip = files[0]
    const appPath = await runningAppPath()
    const root = deps.stagingRoot()
    fs.mkdirSync(root, { recursive: true })

    for (const entry of fs.readdirSync(root)) {
      if (entry.startsWith(MAC_STAGING_PREFIX)) {
        removeTree(path.join(root, entry))
      }
    }

    const dir = fs.mkdtempSync(path.join(root, MAC_STAGING_PREFIX))

    try {
      if (fs.statSync(dir).dev !== fs.statSync(path.dirname(appPath)).dev) {
        throw dmgError(`its folder is on a different disk from ${root}`)
      }

      const needed = (await unpackedBytes(zip)) + GIB
      const free = freeBytes(dir)

      if (free < needed) {
        throw new Error(`Not enough free disk space for the update: ${gib(needed)} GB needed, ${gib(free)} GB free.`)
      }

      progress('Unpacking the macOS update.')
      await run('/usr/bin/ditto', ['-x', '-k', '--noqtn', zip, dir], UNPACK_TIMEOUT_MS)
      const apps = fs.readdirSync(dir).filter((name: string): boolean => name.endsWith('.app'))

      if (apps.length !== 1) {
        throw new Error(`Expected one app in the macOS update, found ${apps.length}`)
      }

      const stagedApp = path.join(dir, apps[0])
      progress('Verifying the signed macOS update.')
      const requirement = await (deps.requirement ?? designatedRequirement)(appPath)
      await run('/usr/bin/codesign', ['--verify', '--deep', '--strict', `-R=${requirement}`, stagedApp], VERIFY_TIMEOUT_MS)

      const plist = path.join(stagedApp, 'Contents/Info.plist')
      const { stdout } = await run('/usr/bin/plutil', ['-extract', 'CFBundleShortVersionString', 'raw', '-o', '-', plist])

      if (stdout.trim() !== version) {
        throw new Error(`The macOS update contains version ${stdout.trim()}, the feed announced ${version}`)
      }

      staged = { appPath, stagedApp, dir, zip }
      deps.log(`[updates] macOS update ${version} staged at ${stagedApp}`)
    } catch (error) {
      removeTree(dir)
      throw error
    }
  }

  const startSwap = async (): Promise<RelaunchWaiterHandle> => {
    const current = staged

    if (!current) {
      throw new Error('No verified macOS update is staged')
    }

    const scriptPath = path.join(current.dir, SWAP_SCRIPT_FILENAME)
    const paramsPath = path.join(current.dir, 'swap.json')
    const readyFile = path.join(current.dir, 'ready')
    // Outside the staging dir, so it survives a cleanup racing a helper that would not die.
    const cancelFile = `${current.dir}.cancelled`
    const logFile = deps.logFile()
    const attempt = path.basename(current.dir)
    fs.mkdirSync(path.dirname(logFile), { recursive: true })
    fs.writeFileSync(scriptPath, SWAP_SCRIPT)
    fs.writeFileSync(
      paramsPath,
      JSON.stringify({
        pid: deps.pid ?? process.pid,
        appPath: current.appPath,
        stagedApp: current.stagedApp,
        dir: current.dir,
        zip: current.zip,
        readyFile,
        cancelFile,
        logFile,
        waitTimeoutMs: deps.waitTimeoutMs ?? DEFAULT_WAIT_TIMEOUT_MS,
        relaunch: (deps.relaunchCommand ?? ((app: string): string[] => ['/usr/bin/open', app]))(current.appPath),
        ps: deps.psCommand ?? ['/bin/ps', '-o', 'lstart=', '-p']
      })
    )

    const env: NodeJS.ProcessEnv = { ...(deps.env ?? process.env), ELECTRON_RUN_AS_NODE: '1', ELECTRON_NO_ASAR: '1' }
    delete env.NODE_OPTIONS
    let child: ChildProcess

    try {
      child = spawn(deps.execPath, [scriptPath, paramsPath], { cwd: current.dir, detached: true, env, stdio: 'ignore' })
    } catch (error) {
      throw new Error(`The macOS update helper did not start: ${errorText(error)}`)
    }

    let closed = false

    const closedPromise = new Promise<void>((resolve: () => void): void => {
      child.once('close', (): void => {
        closed = true
        resolve()
      })
    })

    const ready = await new Promise<boolean>((resolve: (ready: boolean) => void): void => {
      const deadline = Date.now() + handshakeMs
      let settled = false

      const finish = (value: boolean): void => {
        if (!settled) {
          settled = true
          resolve(value)
        }
      }

      child.once('error', (error: Error): void => {
        deps.log(`[updates] macOS update helper failed to start: ${errorText(error)}`)
        finish(false)
      })
      child.once('close', (): void => finish(false))

      const check = (): void => {
        if (settled) {
          return
        }

        if (fs.existsSync(readyFile)) {
          finish(true)
        } else if (Date.now() >= deadline) {
          finish(false)
        } else {
          setTimeout(check, 100)
        }
      }

      check()
    })

    if (!ready) {
      if (!closed) {
        child.kill()
        await Promise.race([closedPromise, new Promise<void>((resolve: () => void) => setTimeout(resolve, 5_000))])
      }

      throw new Error(`The macOS update helper did not start.\n${waiterLogTail(logFile, attempt)}`)
    }

    child.unref()
    helper = child
    let cancellation: Promise<void> | undefined

    const cancel = (): Promise<void> => {
      cancellation ??= (async (): Promise<void> => {
        try {
          fs.writeFileSync(cancelFile, '')
        } catch (error) {
          deps.log(`[updates] macOS update: could not mark the swap as cancelled: ${errorText(error)}`)
        }

        if (!closed) {
          child.kill()
          await Promise.race([closedPromise, new Promise<void>((resolve: () => void) => setTimeout(resolve, 10_000))])
        }

        helper = undefined
        staged = undefined
        removeTree(current.dir)
      })()

      return cancellation
    }

    return { cancel }
  }

  const assertSwapRunning = (): void => {
    if (!helper || helper.exitCode !== null || helper.signalCode !== null) {
      throw new Error('The macOS update helper is no longer running; nothing was installed')
    }
  }

  return { preflight, stage, startSwap, assertSwapRunning }
}

/**
 * The helper. It runs as Node from the installed app's own binary
 * (ELECTRON_RUN_AS_NODE=1, ELECTRON_NO_ASAR=1) and loads every module before
 * it moves the bundle it runs from. `open` hands its environment to the app it
 * starts, so the relaunch drops the two variables or the new version would
 * start as Node too.
 */
export const SWAP_SCRIPT = String.raw`'use strict'
const fs = require('fs')
const path = require('path')
const { spawnSync } = require('child_process')

const p = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'))
const tag = path.basename(p.dir)
const old = p.appPath + '.old'
const ignore = () => {}
const signals = ['SIGTERM', 'SIGINT', 'SIGHUP']

const log = message => {
  try {
    fs.appendFileSync(p.logFile, new Date().toISOString() + ' [' + tag + '] ' + message + '\n')
  } catch (error) {}
}

const reason = error => (error && (error.code || error.message)) || String(error)

const started = pid => {
  const result = spawnSync(p.ps[0], p.ps.slice(1).concat(String(pid)), { encoding: 'utf8' })
  return result.status === 0 ? String(result.stdout).trim() : ''
}

const alive = pid => {
  try {
    process.kill(pid, 0)
    return true
  } catch (error) {
    return error.code === 'EPERM'
  }
}

const remove = target => {
  try {
    fs.rmSync(target, { recursive: true, force: true })
  } catch (error) {
    log('could not remove ' + target + ': ' + reason(error))
  }
}

const relaunch = () => {
  const env = Object.assign({}, process.env)
  delete env.ELECTRON_RUN_AS_NODE
  delete env.ELECTRON_NO_ASAR
  const result = spawnSync(p.relaunch[0], p.relaunch.slice(1), { env, stdio: 'ignore', timeout: 60000 })
  log('relaunch: ' + (result.error ? reason(result.error) : 'exit ' + result.status))
}

const critical = on => signals.forEach(signal => (on ? process.on(signal, ignore) : process.removeListener(signal, ignore)))

const swap = () => {
  if (fs.existsSync(p.cancelFile) || !fs.existsSync(p.stagedApp)) {
    log('cancelled before the swap: nothing replaced')
    return 3
  }

  remove(old)
  critical(true)

  try {
    fs.renameSync(p.appPath, old)
  } catch (error) {
    critical(false)
    log('cannot move the app aside: ' + reason(error) + '; nothing replaced')
    relaunch()
    return 1
  }

  try {
    fs.renameSync(p.stagedApp, p.appPath)
  } catch (error) {
    log('cannot move the new app in: ' + reason(error) + '; restoring the previous app')

    try {
      fs.renameSync(old, p.appPath)
    } catch (restoreError) {
      critical(false)
      log('RESTORE FAILED: ' + reason(restoreError) + '; the previous app is at ' + old)
      return 4
    }

    critical(false)
    log('previous app restored')
    relaunch()
    return 1
  }

  critical(false)
  log('new app in place')
  relaunch()
  remove(old)
  remove(p.dir)
  remove(p.zip)
  log('cleanup done')
  return 0
}

const parentStart = started(p.pid)
const deadline = Date.now() + p.waitTimeoutMs
let polls = 0

const gone = () => {
  if (!alive(p.pid)) {
    return true
  }

  polls += 1

  if (polls % 5 !== 0 || parentStart === '') {
    return false
  }

  // About once a second: the pid may now belong to another process. A failed
  // ps prints nothing and never counts as gone.
  const now = started(p.pid)
  return now !== '' && now !== parentStart
}

const wait = () => {
  if (gone()) {
    const code = swap()
    log('done (' + code + ')')
    process.exit(code)
  }

  if (Date.now() > deadline) {
    log('the app did not quit in time: nothing replaced')
    log('done (2)')
    process.exit(2)
  }

  setTimeout(wait, 200)
}

fs.writeFileSync(p.readyFile, String(process.pid))
log('waiting for pid ' + p.pid + ' to exit')
wait()
`
