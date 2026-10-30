import path from 'node:path'

import { app } from 'electron'
import electronUpdater from 'electron-updater'
import { SemVer } from 'semver'

import feedContract from '../../update-feed.cjs'

import type { ChannelTarget } from './channel'
import { verifyChannelDownload } from './channel-native'
import { channelPublicBase } from './channel-protocol'
import { MacStrategy, type MacStrategyDeps } from './mac'
import { createMacBundleInstaller, SWAP_LOG_FILENAME } from './mac-bundle-install'
import { registerUpdateRelaunch } from './relaunch'

export interface MacClientDeps
  extends Omit<MacStrategyDeps, 'updater' | 'prepareInstall' | 'preflightInstall' | 'relaunch' | 'install'> {
  light: boolean
  feedBaseUrl: string
  /** Exact per-build metadata, not a moving channel directory. */
  feed?: { url: string; channel: string }
  log: (message: string) => void
}

export function createChannelMacStrategy(deps: MacClientDeps, target: ChannelTarget): MacStrategy {
  if (target.package.platform !== 'darwin') {
    throw new Error('Expected macOS channel target')
  }

  return createMacStrategy({
    ...deps,
    channel: target.channel.name,
    feedBaseUrl: target.manifest.request.publicBase,
    feed: { url: target.feedUrl, channel: target.package.feed.channel },
    expectedVersion: target.package.version,
    verifyDownload: (files: string[]): Promise<void> => verifyChannelDownload(files, target.package.artifact)
  })
}

export function createMacStrategy(deps: MacClientDeps): MacStrategy {
  const legacy = feedContract.darwinFeed(deps.channel, deps.light)
  const channel = deps.feed?.channel ?? legacy.channel
  const updater = new electronUpdater.MacUpdater()

  if (deps.feed) {
    // The validated channel sequence, not SemVer precedence, decides whether a
    // pinned build is newer. Build metadata is intentionally precedence-neutral.
    Object.defineProperty(updater, 'currentVersion', {
      value: new SemVer('0.0.0'),
      configurable: true
    })
  }

  updater.autoDownload = false
  updater.autoInstallOnAppQuit = false
  updater.autoRunAppAfterInstall = true
  updater.channel = channel
  updater.allowPrerelease = deps.feed ? Boolean(deps.expectedVersion?.includes('-')) : legacy.allowPrerelease
  // Setting channel enables downgrades in electron-updater. This app never does.
  updater.allowDowngrade = false
  updater.on('error', error => deps.log(`macOS updater: ${error.message}`))

  if (deps.feed) {
    const base = channelPublicBase(deps.feedBaseUrl)
    const url = new URL(channelPublicBase(deps.feed.url))

    if (!deps.feed.url.startsWith(`${base}/`) || url.origin !== new URL(base).origin) {
      throw new Error('Native feed authority mismatch')
    }

    if (!/^[a-z][a-z0-9-]*$/.test(channel) || !url.pathname.endsWith(`/${channel}-mac.yml`)) {
      throw new Error('Invalid macOS feed descriptor')
    }

    updater.setFeedURL({ provider: 'generic', url: new URL('./', url).href, channel })
  } else if (deps.feedBaseUrl) {
    const base = channelPublicBase(deps.feedBaseUrl)
    updater.setFeedURL({ provider: 'generic', url: `${base}/${legacy.directory}/`, channel })
  }

  // Squirrel.Mac reads the whole update zip into memory and crashes past 1 GiB (alfred C0152): the app stages
  // the zip itself and its own signed binary swaps the bundle once this process has quit.
  const installer = createMacBundleInstaller({
    execPath: process.execPath,
    stagingRoot: (): string => path.join(app.getPath('userData'), 'updates'),
    logFile: (): string => path.join(app.getPath('logs'), SWAP_LOG_FILENAME),
    productName: '+Human',
    releasesUrl: 'https://github.com/Blubobo1010/Alfred-Ai-Audit/releases/latest',
    log: deps.log,
    emitProgress: deps.emitProgress
  })

  return new MacStrategy({
    ...deps,
    updater,
    preflightInstall: () => installer.preflight(),
    prepareInstall: (files: string[], version: string) => installer.stage(files, version),
    relaunch: {
      register: () => registerUpdateRelaunch(app, deps.appVersion, { relaunch: () => installer.startSwap() }),
      onManual: (): never => {
        throw new Error('The macOS update helper did not start')
      }
    },
    install: (): void => {
      installer.assertSwapRunning()
      app.quit()
    }
  })
}
