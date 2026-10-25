import type { FlowKind } from '#lib/data/flows';

/** A move back to an app is still a reported switch, not a separate UI category. */
export function reportedSwitchCount(kinds: Partial<Record<FlowKind, number>>): number {
	return (kinds.switch ?? 0) + (kinds.return ?? 0);
}
