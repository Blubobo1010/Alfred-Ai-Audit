import { type ChildProcess, execFileSync, spawn } from 'node:child_process'
import { EventEmitter } from 'node:events'
import * as fs from 'node:fs'
import * as os from 'node:os'
import * as path from 'node:path'

import { afterEach, describe, expect, it, vi } from 'vitest'

import { MacStrategy, type MacStrategyDeps } from './mac'
import {
  createMacBundleInstaller,
  MAC_STAGING_PREFIX,
  type MacBundleInstallerDeps,
  SWAP_LOG_FILENAME
} from './mac-bundle-install'

const cleanups: (() => void)[] = []

afterEach((): void => {
  for (const cleanup of cleanups.splice(0).reverse()) {
    cleanup()
  }
})

function tempRoot(): string {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'mac-swap-')))
  cleanups.push((): void => fs.rmSync(root, { recursive: true, force: true }))

  return root
}

function strategyFixture() {
  const events: string[] = []
  const emitter = new EventEmitter()
  const info = { version: '0.21.708', files: [], releaseDate: '', path: '', sha512: '' }

  const cancel = vi.fn(async (): Promise<void> => {
    events.push('cancel')
  })

  const deps: MacStrategyDeps = {
    updater: {
      checkForUpdates: vi.fn(async () => {
        events.push('check')

        return { isUpdateAvailable: true, updateInfo: info, versionInfo: info }
      }),
      downloadUpdate: vi.fn(async () => {
        events.push('download')

        return ['/updates/Alfred-0.21.708-arm64-mac.zip']
      }),
      quitAndInstall: vi.fn(() => {
        events.push('squirrel')
      }),
      on: emitter.on.bind(emitter) as MacStrategyDeps['updater']['on'],
      removeListener: emitter.removeListener.bind(emitter) as MacStrategyDeps['updater']['removeListener']
    },
    channel: 'stable',
    appVersion: '0.21.707',
    preflightInstall: vi.fn(async (): Promise<void> => {
      events.push('preflight')
    }),
    prepareInstall: vi.fn(async (files: string[], version: string): Promise<void> => {
      events.push(`stage ${files.length} ${version}`)
    }),
    relaunch: {
      register: vi.fn(async () => {
        events.push('helper')

        return { automatic: true, cancel }
      }),
      onManual: vi.fn()
    },
    beforeInstall: vi.fn(async (): Promise<void> => {
      events.push('stop')
    }),
    onInstallFailure: vi.fn(async (): Promise<void> => {
      events.push('restore')
    }),
    install: vi.fn((): void => {
      events.push('quit')
    }),
    emitProgress: vi.fn()
  }

  return { deps, events, strategy: new MacStrategy(deps) }
}

describe('macOS strategy without Squirrel', () => {
  it('stages the update and starts the helper before anything is stopped', async (): Promise<void> => {
    const { deps, events, strategy } = strategyFixture()
    expect(await strategy.apply()).toMatchObject({ ok: true, handedOff: true })
    expect(events).toEqual(['check', 'preflight', 'download', 'stage 1 0.21.708', 'helper', 'stop', 'quit'])
    expect(deps.updater.quitAndInstall).not.toHaveBeenCalled()
  })

  it('downloads nothing when the preflight refuses', async (): Promise<void> => {
    const { deps, events, strategy } = strategyFixture()
    vi.mocked(deps.preflightInstall).mockRejectedValueOnce(new Error('install from the DMG'))
    await expect(strategy.apply()).rejects.toThrow('install from the DMG')
    expect(deps.preflightInstall).toHaveBeenCalledOnce()
    expect(deps.updater.downloadUpdate).not.toHaveBeenCalled()
    expect(events).toEqual(['check'])
  })

  it('cancels the helper and restores the backend when the teardown fails', async (): Promise<void> => {
    const { deps, events, strategy } = strategyFixture()
    vi.mocked(deps.beforeInstall).mockRejectedValueOnce(new Error('backend did not stop'))
    await expect(strategy.apply()).rejects.toThrow('backend did not stop')
    expect(events.slice(-3)).toEqual(['helper', 'cancel', 'restore'])
    expect(events).not.toContain('quit')
  })

  it('does not quit when the helper is gone', async (): Promise<void> => {
    const { deps, events, strategy } = strategyFixture()
    vi.mocked(deps.install).mockImplementationOnce((): never => {
      throw new Error('helper is no longer running')
    })
    await expect(strategy.apply()).rejects.toThrow('helper is no longer running')
    expect(events.slice(-3)).toEqual(['stop', 'cancel', 'restore'])
  })
})

function bareApp(dir: string): string {
  const app = path.join(dir, 'Alfred.app')
  fs.mkdirSync(path.join(app, 'Contents/MacOS'), { recursive: true })
  fs.writeFileSync(path.join(app, 'Contents/MacOS/Alfred'), '')

  return app
}

function installer(appPath: string, overrides: Partial<MacBundleInstallerDeps> = {}) {
  return createMacBundleInstaller({
    execPath: path.join(appPath, 'Contents/MacOS/Alfred'),
    stagingRoot: (): string => path.join(path.dirname(path.dirname(appPath)), 'userData/updates'),
    logFile: (): string => path.join(path.dirname(path.dirname(appPath)), 'Logs', SWAP_LOG_FILENAME),
    productName: 'Alfred',
    releasesUrl: 'https://example.test/releases/latest',
    log: vi.fn(),
    emitProgress: vi.fn(),
    ...overrides
  })
}

describe.skipIf(process.platform === 'win32')('macOS update preflight', () => {
  it('refuses a translocated copy and points to the DMG', async (): Promise<void> => {
    const app = bareApp(path.join(tempRoot(), 'AppTranslocation/0A1B/d'))
    await expect(installer(app).preflight()).rejects.toThrow(
      /cannot update itself here: macOS is running it from a temporary read-only copy.*DMG: https:\/\/example\.test/
    )
  })

  it.skipIf(process.getuid?.() === 0)('refuses a folder this user cannot write', async (): Promise<void> => {
    const locked = path.join(tempRoot(), 'Locked')
    const app = bareApp(locked)
    fs.chmodSync(locked, 0o555)
    cleanups.push((): void => fs.chmodSync(locked, 0o755))
    await expect(installer(app).preflight()).rejects.toThrow(`${locked} is not writable by this user`)
  })

  it('removes a copy left aside by an earlier update', async (): Promise<void> => {
    const app = bareApp(path.join(tempRoot(), 'Applications'))
    fs.mkdirSync(`${app}.old/Contents`, { recursive: true })
    await installer(app).preflight()
    expect(fs.existsSync(`${app}.old`)).toBe(false)
  })
})

function signedApp(dir: string, version: string, identifier: string): string {
  const app = path.join(dir, 'Alfred.app')
  fs.mkdirSync(path.join(app, 'Contents/MacOS'), { recursive: true })
  fs.copyFileSync('/usr/bin/true', path.join(app, 'Contents/MacOS/Alfred'))
  const plist = path.join(app, 'Contents/Info.plist')
  execFileSync('/usr/bin/plutil', ['-create', 'xml1', plist])

  for (const [key, value] of [
    ['CFBundleIdentifier', identifier],
    ['CFBundleExecutable', 'Alfred'],
    ['CFBundleShortVersionString', version]
  ]) {
    execFileSync('/usr/bin/plutil', ['-insert', key, '-string', value, plist])
  }

  execFileSync('/usr/bin/codesign', ['-s', '-', '--force', '-i', identifier, app], { stdio: 'ignore' })

  return app
}

function bundleVersion(app: string): string {
  return execFileSync('/usr/bin/plutil', [
    '-extract',
    'CFBundleShortVersionString',
    'raw',
    '-o',
    '-',
    path.join(app, 'Contents/Info.plist')
  ])
    .toString()
    .trim()
}

function fakeApp(): ChildProcess {
  const child = spawn('/bin/sleep', ['60'], { stdio: 'ignore' })
  cleanups.push((): void => {
    child.kill()
  })

  return child
}

async function waitForLog(file: string, text: string, timeoutMs: number = 15_000): Promise<string> {
  const deadline = Date.now() + timeoutMs

  for (;;) {
    const log = fs.existsSync(file) ? fs.readFileSync(file, 'utf8') : ''

    if (log.includes(text)) {
      return log
    }

    if (Date.now() > deadline) {
      throw new Error(`no "${text}" in ${file}:\n${log}`)
    }

    await new Promise<void>((resolve: () => void) => setTimeout(resolve, 100))
  }
}

function swapWorld(stagedVersion: string = '2.0', stagedIdentifier: string = 'com.test.swap') {
  const root = tempRoot()
  const applications = path.join(root, 'Applications')
  const build = path.join(root, 'build')
  fs.mkdirSync(applications)
  fs.mkdirSync(build)
  const app = signedApp(applications, '1.0', 'com.test.swap')
  const zip = path.join(root, 'Alfred-2.0-arm64-mac.zip')
  execFileSync('/usr/bin/ditto', ['-c', '-k', '--keepParent', signedApp(build, stagedVersion, stagedIdentifier), zip])
  const parent = fakeApp()
  const logFile = path.join(root, 'Logs', SWAP_LOG_FILENAME)
  const envFile = path.join(root, 'relaunch-env.txt')
  const staging = path.join(root, 'userData/updates')

  const swap = (overrides: Partial<MacBundleInstallerDeps> = {}) =>
    installer(app, {
      requirement: async (): Promise<string> => 'identifier "com.test.swap"',
      spawn: (_command, args, options) => spawn(process.execPath, args, options),
      relaunchCommand: (): string[] => ['/bin/sh', '-c', 'env > "$0"', envFile],
      pid: parent.pid,
      ...overrides
    })

  const stagingDirs = (): string[] =>
    fs.existsSync(staging) ? fs.readdirSync(staging).filter((name: string) => name.startsWith(MAC_STAGING_PREFIX)) : []

  return { app, envFile, logFile, parent, staging, stagingDirs, swap, zip }
}

describe.skipIf(process.platform !== 'darwin')('macOS bundle swap', { timeout: 60_000 }, () => {
  it('replaces the app once it has quit and relaunches it without the Node switches', async (): Promise<void> => {
    const world = swapWorld()
    const install = world.swap()
    await install.preflight()
    await install.stage([world.zip], '2.0')
    await install.startSwap()
    install.assertSwapRunning()
    expect(bundleVersion(world.app)).toBe('1.0')
    world.parent.kill()
    await waitForLog(world.logFile, 'done (0)')
    expect(bundleVersion(world.app)).toBe('2.0')
    expect(fs.existsSync(`${world.app}.old`)).toBe(false)
    expect(world.stagingDirs()).toEqual([])
    expect(fs.existsSync(world.zip)).toBe(false)
    const env = fs.readFileSync(world.envFile, 'utf8')
    expect(env).not.toMatch(/^ELECTRON_RUN_AS_NODE=/m)
    expect(env).not.toMatch(/^ELECTRON_NO_ASAR=/m)
  })

  it('puts the previous app back when the new one cannot be moved in', async (): Promise<void> => {
    const world = swapWorld()
    const install = world.swap()
    await install.stage([world.zip], '2.0')
    await install.startSwap()
    const locked = path.join(world.staging, world.stagingDirs()[0])
    fs.chmodSync(locked, 0o555)
    cleanups.push((): void => fs.chmodSync(locked, 0o755))
    world.parent.kill()
    const log = await waitForLog(world.logFile, 'done (1)')
    expect(log).toContain('previous app restored')
    expect(bundleVersion(world.app)).toBe('1.0')
    expect(fs.existsSync(`${world.app}.old`)).toBe(false)
    expect(fs.existsSync(world.envFile)).toBe(true)
  })

  it('refuses an update signed by someone else', async (): Promise<void> => {
    const world = swapWorld('2.0', 'com.test.other')
    await expect(world.swap().stage([world.zip], '2.0')).rejects.toThrow('codesign')
    expect(world.stagingDirs()).toEqual([])
  })

  it('refuses an update whose version differs from the feed', async (): Promise<void> => {
    const world = swapWorld()
    await expect(world.swap().stage([world.zip], '2.1')).rejects.toThrow('contains version 2.0, the feed announced 2.1')
    expect(world.stagingDirs()).toEqual([])
  })

  it('refuses an update without enough free space', async (): Promise<void> => {
    const world = swapWorld()
    await expect(world.swap({ freeBytes: (): number => 0 }).stage([world.zip], '2.0')).rejects.toThrow(
      'Not enough free disk space'
    )
  })

  it('leaves the app alone when it does not quit in time', async (): Promise<void> => {
    const world = swapWorld()
    const install = world.swap({ waitTimeoutMs: 600 })
    await install.stage([world.zip], '2.0')
    await install.startSwap()
    const log = await waitForLog(world.logFile, 'done (2)')
    expect(log).toContain('did not quit in time')
    expect(bundleVersion(world.app)).toBe('1.0')
  })

  it('swaps when the pid now belongs to another process', async (): Promise<void> => {
    const world = swapWorld()
    const counter = path.join(world.staging, '..', 'ps-counter')

    const install = world.swap({
      psCommand: ['/bin/sh', '-c', 'n=$(cat "$0" 2>/dev/null || echo 0); echo $((n + 1)) > "$0"; echo "start $n"', counter]
    })

    await install.stage([world.zip], '2.0')
    await install.startSwap()
    await waitForLog(world.logFile, 'done (0)')
    expect(bundleVersion(world.app)).toBe('2.0')
  })

  it('does nothing after a cancel, even once the app quits', async (): Promise<void> => {
    const world = swapWorld()
    const install = world.swap()
    await install.stage([world.zip], '2.0')
    const handle = await install.startSwap()
    const attempt = world.stagingDirs()[0]
    await handle.cancel()
    expect(() => install.assertSwapRunning()).toThrow('no longer running')
    expect(fs.existsSync(path.join(world.staging, `${attempt}.cancelled`))).toBe(true)
    world.parent.kill()
    await new Promise<void>((resolve: () => void) => setTimeout(resolve, 1_500))
    expect(bundleVersion(world.app)).toBe('1.0')
    expect(fs.readFileSync(world.logFile, 'utf8')).not.toContain('new app in place')
  })
})
