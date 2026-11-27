import type { RosterRow } from './types'

interface HubSkillsSectionProps {
  /** Existing bot to route through; omitted for the launch profile at create time. */
  bot?: RosterRow
  onInstalled?: (name: string) => void
}

/** Upstream embeds its documentation site's skills hub here (an iframe of an
 *  outside page whose cards install third-party skills) next to a hub search.
 *  This build offers a bot the skills that are already installed; new ones are
 *  added from the CLI. The component stays so both editors mount it unchanged:
 *  it renders nothing, loads nothing and listens to nothing. */
export function HubSkillsSection(_props: HubSkillsSectionProps) {
  return null
}
