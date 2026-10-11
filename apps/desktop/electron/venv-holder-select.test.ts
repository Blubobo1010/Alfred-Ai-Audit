import assert from 'node:assert/strict'

import { test } from 'vitest'

import { hasWindowsPathPrefix, isExternalVenvHolder, isHermesOwnedVenvDaemon } from './venv-holder-select'

const SCRIPTS = 'C:\\Alfred\\venv\\Scripts'

test('matches the hindsight daemon shim (exe under venv Scripts + hindsight cmdline)', () => {
  assert.equal(
    isHermesOwnedVenvDaemon(
      'C:\\Alfred\\venv\\Scripts\\pythonw.exe',
      'C:\\Alfred\\venv\\Scripts\\pythonw.exe -m hindsight_api.main --daemon --idle-timeout 300 --port 9177',
      SCRIPTS
    ),
    true
  )
})

test('Windows path prefix match is ordinal case-insensitive', () => {
  assert.equal(
    isHermesOwnedVenvDaemon(
      'c:\\hermes\\venv\\scripts\\python.exe',
      'python.exe -m hindsight_api.main --daemon',
      'C:\\Alfred\\venv\\Scripts'
    ),
    true
  )
})

test('excludes external venv holders that are not the hindsight daemon', () => {
  // a user terminal running the hermes CLI from the venv — must NOT be killed
  assert.equal(isHermesOwnedVenvDaemon('C:\\Alfred\\venv\\Scripts\\hermes.exe', 'alfred chat -q "hi"', SCRIPTS), false)
  // an unrelated python script using the venv interpreter
  assert.equal(
    isHermesOwnedVenvDaemon('C:\\Alfred\\venv\\Scripts\\python.exe', 'python C:\\tools\\import.py', SCRIPTS),
    false
  )
})

test('excludes exes outside the venv even when the cmdline mentions hindsight', () => {
  assert.equal(
    isHermesOwnedVenvDaemon('C:\\Other\\pythonw.exe', 'pythonw -m hindsight_api.main --daemon', SCRIPTS),
    false
  )
})

test('prefix boundary: sibling dirs (ScriptsX) do not match', () => {
  assert.equal(hasWindowsPathPrefix('C:\\Alfred\\venv\\ScriptsX\\python.exe', SCRIPTS), false)
  assert.equal(hasWindowsPathPrefix('C:\\Alfred\\venv\\Scripts\\python.exe', SCRIPTS), true)
})

test('null/undefined fields never match', () => {
  assert.equal(isHermesOwnedVenvDaemon(null, 'x', SCRIPTS), false)
  assert.equal(isHermesOwnedVenvDaemon('C:\\Alfred\\venv\\Scripts\\pythonw.exe', null, SCRIPTS), false)
  assert.equal(isHermesOwnedVenvDaemon(undefined, undefined, SCRIPTS), false)
})

// --- isExternalVenvHolder (#62311) ------------------------------------------

test('matches the autostart gateway shim (hermes.exe under venv Scripts)', () => {
  assert.equal(
    isExternalVenvHolder(
      'C:\\Alfred\\venv\\Scripts\\hermes.exe',
      '"C:\\Alfred\\venv\\Scripts\\hermes.exe" gateway run --external-supervisor',
      SCRIPTS
    ),
    true
  )
})

test('matches the dashboard scheduled task (python -m hermes_cli / -m hermes)', () => {
  assert.equal(
    isExternalVenvHolder(
      'C:\\Alfred\\venv\\Scripts\\python.exe',
      '"C:\\Alfred\\venv\\Scripts\\python.exe" -m hermes_cli.main dashboard',
      SCRIPTS
    ),
    true
  )
  assert.equal(
    isExternalVenvHolder('C:\\Alfred\\venv\\Scripts\\pythonw.exe', 'pythonw.exe -m alfred serve', SCRIPTS),
    true
  )
})

test('never matches an unrelated process that merely borrows the venv interpreter', () => {
  // a user's own script running on the venv python — NOT Alfred, must NOT be killed
  assert.equal(
    isExternalVenvHolder('C:\\Alfred\\venv\\Scripts\\python.exe', 'python C:\\tools\\import.py', SCRIPTS),
    false
  )
  // hindsight daemon is selected by isHermesOwnedVenvDaemon, not here
  assert.equal(
    isExternalVenvHolder('C:\\Alfred\\venv\\Scripts\\pythonw.exe', 'pythonw -m hindsight_api.main --daemon', SCRIPTS),
    false
  )
})

test('never matches a process outside the venv, even with hermes in the cmdline', () => {
  // an editor / shell whose command line mentions the install root (#62445 regression guard)
  assert.equal(
    isExternalVenvHolder('C:\\Windows\\System32\\cmd.exe', 'cmd /c cd C:\\Alfred\\venv\\Scripts && dir', SCRIPTS),
    false
  )
  assert.equal(isExternalVenvHolder('C:\\Other\\hermes.exe', 'alfred gateway run', SCRIPTS), false)
})

test('sibling-dir and boundary safety for the external selector', () => {
  assert.equal(isExternalVenvHolder('C:\\Alfred\\venv\\ScriptsX\\hermes.exe', 'alfred gateway run', SCRIPTS), false)
  assert.equal(isExternalVenvHolder(null, 'alfred gateway run', SCRIPTS), false)
  assert.equal(isExternalVenvHolder('C:\\Alfred\\venv\\Scripts\\hermes.exe', null, SCRIPTS), false)
})
