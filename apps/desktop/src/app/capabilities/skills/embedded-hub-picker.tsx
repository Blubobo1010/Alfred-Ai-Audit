import { memo } from 'react'

import type { ProfileScope } from '@/hermes'

interface EmbeddedHubPickerProps {
  hidden?: boolean
  installedNames: ReadonlySet<string>
  profile?: ProfileScope
}

/** Upstream embeds its documentation site's skills hub here: an iframe of an
 *  outside page where one click on a card installs a third-party skill, with
 *  no confirmation. This build lists installed skills only; skills are added
 *  from the CLI. The component stays so the Capabilities view mounts it
 *  unchanged: it renders nothing, loads nothing and listens to nothing. */
export const EmbeddedHubPicker = memo(function EmbeddedHubPicker(_props: EmbeddedHubPickerProps) {
  return null
})
