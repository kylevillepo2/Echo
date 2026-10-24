<script lang="ts">
	import { ENV_BASE, type ApiMode } from '#lib/api';
	import { studio } from '#lib/state/studio.svelte';

	let mode = $state<ApiMode>(studio.mode);
	let base = $state(studio.apiBase || ENV_BASE);
	let testing = $state(false);
	let connecting = $state(false);
	let testResult = $state<{ ok: boolean; detail?: string } | null>(null);
	let showContract = $state(false);

	const meta = $derived(studio.meta);

	async function test() {
		if (!base.trim()) return;
		testing = true;
		testResult = null;
		testResult = await studio.testConnection(base.trim());
		testing = false;
	}

	async function connect() {
		connecting = true;
		await studio.setMode(mode, mode === 'live' ? base.trim() : '');
		connecting = false;
		if (!studio.error) studio.connectOpen = false;
	}

	function pick(next: ApiMode) {
		mode = next;
		testResult = null;
	}
</script>

<div
	class="backdrop"
	role="presentation"
	onclick={(event) => {
		if (event.target === event.currentTarget) studio.connectOpen = false;
	}}
>
	<div class="dialog" role="dialog" aria-modal="true" aria-label="Connect data source">
		<header>
			<div>
				<span class="label">Data source</span>
				<h2>Connect your corpus</h2>
			</div>
			<button class="close" onclick={() => (studio.connectOpen = false)} aria-label="Close">×</button>
		</header>

		<div class="body scroll">
			<div class="options">
				<button class="option" class:active={mode === 'demo'} onclick={() => pick('demo')}>
					<div class="option-top">
						<span class="radio" class:on={mode === 'demo'}></span>
						<span class="option-name">Demo corpus</span>
						<span class="chip">offline</span>
					</div>
					<p>
						Seeded multi-category dataset for exploring the interface. {meta?.appCount ?? 60} apps,
						{meta?.categoryCount ?? 12} category clusters, {meta?.sampled?.toLocaleString() ?? '9,000'} sampled
						reviews.
					</p>
				</button>

				<button class="option" class:active={mode === 'live'} onclick={() => pick('live')}>
					<div class="option-top">
						<span class="radio" class:on={mode === 'live'}></span>
						<span class="option-name">Live API</span>
						<span class="chip is-lime">your backend</span>
					</div>
					<p>
						Point the app at your graph, review and semantic-search endpoints. Nothing else in the
						interface changes.
					</p>
				</button>
			</div>

			{#if mode === 'live'}
				<div class="field">
					<label for="api-base">API base URL</label>
					<div class="input-row">
						<input
							id="api-base"
							class="input"
							type="url"
							placeholder="http://localhost:8000/api"
							bind:value={base}
							spellcheck="false"
						/>
						<button class="btn is-sm" onclick={test} disabled={testing || !base.trim()}>
							{testing ? 'Testing…' : 'Test'}
						</button>
					</div>
					{#if testResult}
						<div class="test-result" class:ok={testResult.ok} class:bad={!testResult.ok}>
							<span class="dot"></span>
							{testResult.ok
								? `Reachable${testResult.detail ? ` · ${testResult.detail}` : ''}`
								: `Not reachable${testResult.detail ? ` · ${testResult.detail}` : ''}`}
						</div>
					{:else}
						<p class="hint">
							CORS must allow this origin. The base path is prefixed to every route below.
						</p>
					{/if}
				</div>

				<button class="contract-toggle" onclick={() => (showContract = !showContract)}>
					{showContract ? 'Hide' : 'Show'} expected endpoints
					<span class="arrow" class:open={showContract}>▾</span>
				</button>

				{#if showContract}
					<div class="contract">
						<div class="route"><span class="verb">GET</span><code>/health</code><span>liveness probe</span></div>
						<div class="route"><span class="verb">GET</span><code>/graph</code><span>categories, apps, edges, meta</span></div>
						<div class="route">
							<span class="verb">GET</span><code>/apps/:id/reviews</code><span>?limit=&amp;stars=</span>
						</div>
						<div class="route">
							<span class="verb">GET</span><code>/search</code><span>?q=&amp;appId=&amp;limit=</span>
						</div>
						<p class="contract-note">
							Full JSON shapes are documented in <code>API.md</code>. Edit
							<code>src/lib/api/http.ts</code> if your routes differ.
						</p>
					</div>
				{/if}
			{/if}

			{#if studio.error}
				<div class="error" role="alert">
					<span class="label">Connection error</span>
					<p>{studio.error}</p>
				</div>
			{/if}
		</div>

		<footer>
			<span class="foot-note">
				{studio.mode === 'live' ? 'Currently live' : 'Currently demo'}
			</span>
			<button class="btn is-ghost" onclick={() => (studio.connectOpen = false)}>Cancel</button>
			<button
				class="btn is-active"
				onclick={connect}
				disabled={connecting || (mode === 'live' && !base.trim())}
			>
				{connecting ? 'Connecting…' : mode === 'live' ? 'Connect API' : 'Use demo data'}
			</button>
		</footer>
	</div>
</div>

<style>
	.backdrop {
		position: fixed;
		inset: 0;
		z-index: 110;
		background: rgba(4, 4, 6, 0.7);
		backdrop-filter: blur(3px);
		display: flex;
		align-items: center;
		justify-content: center;
		padding: 20px;
	}
	.dialog {
		width: min(560px, 94vw);
		max-height: 88vh;
		display: flex;
		flex-direction: column;
		background: var(--panel);
		border: 1px solid var(--line-bright);
		border-radius: 3px;
		box-shadow: 0 40px 120px rgba(0, 0, 0, 0.7);
		overflow: hidden;
	}
	header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		padding: 16px 16px 13px;
		border-bottom: 1px solid var(--line);
	}
	header h2 {
		margin: 6px 0 0;
		font-size: 19px;
		font-weight: 600;
		letter-spacing: -0.015em;
	}
	.close {
		width: 24px;
		height: 24px;
		display: grid;
		place-items: center;
		font-size: 18px;
		color: var(--dim);
		border: 1px solid transparent;
		border-radius: 2px;
	}
	.close:hover {
		color: var(--text);
		border-color: var(--line-strong);
	}

	.body {
		padding: 14px 16px;
		overflow-y: auto;
	}
	.options {
		display: flex;
		flex-direction: column;
		gap: 8px;
	}
	.option {
		text-align: left;
		padding: 11px 12px;
		border: 1px solid var(--line);
		border-radius: 2px;
		background: var(--bg-soft);
		transition:
			border-color var(--fast),
			background var(--fast);
	}
	.option:hover {
		border-color: var(--line-strong);
	}
	.option.active {
		border-color: var(--lime);
		background: color-mix(in srgb, var(--lime) 4%, var(--bg-soft));
	}
	.option-top {
		display: flex;
		align-items: center;
		gap: 7px;
	}
	.radio {
		width: 9px;
		height: 9px;
		border: 1px solid var(--line-bright);
		border-radius: 50%;
		flex: none;
	}
	.radio.on {
		border-color: var(--lime);
		background: radial-gradient(circle at center, var(--lime) 0 3px, transparent 3px);
	}
	.option-name {
		font-size: 12.5px;
		font-weight: 500;
		color: var(--text);
	}
	.option-top .chip {
		margin-left: auto;
		height: 18px;
		font-size: 8px;
	}
	.option p {
		margin: 6px 0 0 16px;
		font-size: 11px;
		line-height: 1.5;
		color: var(--muted);
	}

	.field {
		margin-top: 16px;
	}
	.field label {
		display: block;
		font-family: var(--mono);
		font-size: 9px;
		letter-spacing: 0.1em;
		text-transform: uppercase;
		color: var(--muted);
		margin-bottom: 6px;
	}
	.input-row {
		display: flex;
		gap: 7px;
	}
	.input-row .input {
		flex: 1;
	}
	.test-result {
		display: flex;
		align-items: center;
		gap: 6px;
		margin-top: 7px;
		font-family: var(--mono);
		font-size: 9px;
	}
	.test-result .dot {
		width: 5px;
		height: 5px;
		border-radius: 50%;
		background: currentColor;
	}
	.test-result.ok {
		color: var(--pos);
	}
	.test-result.bad {
		color: var(--neg);
	}
	.hint {
		margin: 6px 0 0;
		font-size: 10px;
		color: var(--faint);
	}

	.contract-toggle {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		margin-top: 14px;
		font-family: var(--mono);
		font-size: 9px;
		letter-spacing: 0.04em;
		color: var(--muted);
	}
	.contract-toggle:hover {
		color: var(--text-2);
	}
	.arrow {
		font-size: 8px;
		transition: transform var(--fast);
	}
	.arrow.open {
		transform: rotate(180deg);
	}
	.contract {
		margin-top: 8px;
		border: 1px solid var(--line);
		background: var(--bg-soft);
		padding: 8px 10px;
	}
	.route {
		display: flex;
		align-items: center;
		gap: 7px;
		padding: 4px 0;
		font-family: var(--mono);
		font-size: 9px;
		border-bottom: 1px dashed var(--line);
	}
	.route:last-of-type {
		border-bottom: 0;
	}
	.verb {
		color: var(--lime);
		font-size: 8px;
	}
	.route code {
		color: var(--text-2);
	}
	.route span:last-child {
		margin-left: auto;
		color: var(--faint);
		font-size: 8px;
	}
	.contract-note {
		margin: 8px 0 0;
		font-size: 9.5px;
		line-height: 1.5;
		color: var(--dim);
	}
	.contract-note code {
		font-family: var(--mono);
		color: var(--muted);
	}

	.error {
		margin-top: 14px;
		padding: 9px 10px;
		border: 1px solid color-mix(in srgb, var(--neg) 35%, var(--line));
		background: color-mix(in srgb, var(--neg) 6%, transparent);
	}
	.error p {
		margin: 4px 0 0;
		font-family: var(--mono);
		font-size: 9.5px;
		line-height: 1.5;
		color: var(--neg);
		word-break: break-word;
	}

	footer {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 11px 16px;
		border-top: 1px solid var(--line);
		background: var(--bg-soft);
	}
	.foot-note {
		flex: 1;
		font-family: var(--mono);
		font-size: 8.5px;
		color: var(--dim);
	}
</style>
