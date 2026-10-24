<script lang="ts">
	import { studio } from '#lib/state/studio.svelte';
	import { fmtCount } from '#lib/utils/format';

	const shortcuts = [
		{ keys: ['⌘', 'K'], label: 'Open semantic search' },
		{ keys: ['/'], label: 'Focus search' },
		{ keys: ['1'], label: 'Network view' },
		{ keys: ['2'], label: 'Theme ledger' },
		{ keys: ['I'], label: 'Toggle inspector' },
		{ keys: ['↑', '↓'], label: 'Move through results' },
		{ keys: ['↵'], label: 'Inspect selection' },
		{ keys: ['Esc'], label: 'Close overlays / clear selection' }
	];
</script>

<div
	class="backdrop"
	role="presentation"
	onclick={(event) => {
		if (event.target === event.currentTarget) studio.helpOpen = false;
	}}
>
	<div class="sheet" role="dialog" aria-modal="true" aria-label="Help and shortcuts">
		<header>
			<div>
				<span class="label">Field guide</span>
				<h2>How UNWRAP works</h2>
			</div>
			<button class="close" onclick={() => (studio.helpOpen = false)} aria-label="Close">×</button>
		</header>

		<div class="body scroll">
			<div class="pipeline">
				<div class="step">
					<span class="step-num num">01</span>
					<div>
						<h3>Ingest</h3>
						<p>
							Your CSV lands in the backend. Each review keeps its app, category, stars, date,
							source and version.
						</p>
					</div>
				</div>
				<div class="step">
					<span class="step-num num">02</span>
					<div>
						<h3>Embed &amp; cluster</h3>
						<p>
							Reviews become vectors. Similar neighbours, recurring themes and a 2D projection come
							back through the API as graph nodes and edges.
						</p>
					</div>
				</div>
				<div class="step">
					<span class="step-num num">03</span>
					<div>
						<h3>Unwrap</h3>
						<p>
							Categories are dashed clusters, apps are circles. Click a cluster to focus only its
							apps; click an app for reception, themes and raw reviews.
						</p>
					</div>
				</div>
			</div>

			<div class="section">
				<span class="label">Reading the map</span>
				<div class="legend-grid">
					<div class="legend-item">
						<span class="shape cl"></span>
						<div><b>Category cluster</b><span>Click to focus only its apps</span></div>
					</div>
					<div class="legend-item">
						<span class="shape ci"></span>
						<div><b>App node</b><span>Size = review volume or downloads/day</span></div>
					</div>
					<div class="legend-item">
						<span class="line sim"></span>
						<div><b>Similarity edge</b><span>Shared review vocabulary &amp; themes</span></div>
					</div>
					<div class="legend-item">
						<span class="ring"></span>
						<div><b>Reception ring</b><span>Arc = 0–100 composite score</span></div>
					</div>
				</div>
			</div>

			<div class="section">
				<span class="label">Gestures</span>
				<ul class="gestures">
					<li><b>Scroll</b> zoom the map</li>
					<li><b>Drag</b> pan, or move a node</li>
					<li><b>Hover</b> preview a node or cluster</li>
					<li><b>Click a cluster</b> narrow the map to that category</li>
					<li><b>Double-click</b> release a pinned node</li>
				</ul>
			</div>

			<div class="section">
				<span class="label">Downloads &amp; signals</span>
				<div class="method">
					<p>
						Lifetime installs are anchored to Google Play's public install bracket and Apple's US
						rating counts. The 26-week series and daily rate are modelled from those anchors, then
						marked <b class="est">est.</b> — they are directional demo numbers, not measured daily
						installs.
					</p>
					<p>
						Review dates are sampled around the download curve. The inspector and theme ledger show
						the weekly Pearson correlation <code>r</code> between a review signal and downloads.
						<b>leads</b> means the review signal moved first; <b>lags</b> means installs moved first.
						Treat the result as exploratory, not causal.
					</p>
				</div>
			</div>

			<div class="section">
				<span class="label">Keyboard</span>
				<div class="keys">
					{#each shortcuts as shortcut}
						<div class="key-row">
							<span class="combo">
								{#each shortcut.keys as key}
									<kbd>{key}</kbd>
								{/each}
							</span>
							<span>{shortcut.label}</span>
						</div>
					{/each}
				</div>
			</div>

			<div class="note">
				<span class="label">About this dataset</span>
				<p>
					The demo corpus is seeded from a 60-app app-store export across 12 category clusters, with
					{fmtCount(studio.meta?.reviewCount ?? 0)} indexed reviews and
					{fmtCount(studio.meta?.sampled ?? 0)} sampled reviews. Ratings, platform splits, trends and themes
					are plausible demo metadata generated locally so the map is stable. Reception is a composite
					of star distribution, sentiment mix and an 8-week trend. Themes are grouped review clusters,
					not raw keyword counts.
				</p>
				<p>
					When you connect a live API, all numbers and copy come from your backend. The UI reads
					<code>meta.embeddingDim</code> and <code>meta.embeddingModel</code> for the status bar.
				</p>
			</div>
		</div>

		<footer>
			<span class="foot">UNWRAP · hackathon build</span>
			<button class="btn is-sm" onclick={() => (studio.helpOpen = false)}>Close</button>
		</footer>
	</div>
</div>

<style>
	.backdrop {
		position: fixed;
		inset: 0;
		z-index: 105;
		background: rgba(4, 4, 6, 0.7);
		backdrop-filter: blur(3px);
		display: flex;
		align-items: center;
		justify-content: center;
		padding: 20px;
	}
	.sheet {
		width: min(620px, 94vw);
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
		overflow-y: auto;
		padding: 16px;
	}

	.pipeline {
		display: flex;
		flex-direction: column;
		gap: 12px;
		padding-bottom: 16px;
		border-bottom: 1px solid var(--line);
	}
	.step {
		display: flex;
		gap: 10px;
	}
	.step-num {
		font-size: 9px;
		color: var(--lime);
		padding-top: 2px;
		width: 20px;
		flex: none;
	}
	.step h3 {
		margin: 0 0 3px;
		font-size: 12.5px;
		font-weight: 500;
		color: var(--text);
	}
	.step p {
		margin: 0;
		font-size: 11.5px;
		line-height: 1.55;
		color: var(--muted);
		max-width: 440px;
	}

	.section {
		padding: 14px 0;
		border-bottom: 1px solid var(--line);
	}
	.section > .label {
		display: block;
		margin-bottom: 9px;
	}
	.method p {
		margin: 0 0 8px;
		font-size: 10.5px;
		line-height: 1.6;
		color: var(--dim);
	}
	.method p:last-child {
		margin-bottom: 0;
	}
	.method b {
		color: var(--text-2);
		font-weight: 500;
	}
	.method b.est {
		color: var(--amber);
		font-family: var(--mono);
		font-size: 9px;
		letter-spacing: 0.06em;
		text-transform: uppercase;
	}
	.method code {
		font-family: var(--mono);
		font-size: 9.5px;
		color: var(--muted);
	}

	.legend-grid {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 10px 14px;
	}
	.legend-item {
		display: flex;
		align-items: flex-start;
		gap: 8px;
	}
	.legend-item b {
		display: block;
		font-size: 11px;
		font-weight: 500;
		color: var(--text-2);
	}
	.legend-item span {
		display: block;
		font-size: 9.5px;
		color: var(--dim);
	}
	.shape {
		width: 11px;
		height: 11px;
		margin-top: 2px;
		flex: none;
	}
	.shape.cl {
		border-radius: 50%;
		border: 1px dashed var(--cyan);
		background: color-mix(in srgb, var(--cyan) 12%, transparent);
	}
	.shape.ci {
		border-radius: 50%;
		border: 1px solid var(--lime);
		background: color-mix(in srgb, var(--lime) 18%, transparent);
	}
	.line {
		width: 14px;
		border-top: 1px dashed var(--lime);
		margin-top: 6px;
		flex: none;
	}
	.ring {
		width: 11px;
		height: 11px;
		border-radius: 50%;
		border: 1px solid var(--pos);
		border-right-color: transparent;
		margin-top: 2px;
		flex: none;
	}

	.gestures {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 6px 16px;
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.gestures li {
		font-size: 10.5px;
		color: var(--muted);
	}
	.gestures b {
		color: var(--text-2);
		font-weight: 500;
	}

	.keys {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 6px 18px;
	}
	.key-row {
		display: flex;
		align-items: center;
		gap: 8px;
		font-size: 10.5px;
		color: var(--muted);
	}
	.combo {
		display: inline-flex;
		gap: 2px;
		min-width: 46px;
	}
	kbd {
		font-family: var(--mono);
		font-size: 8px;
		color: var(--text-2);
		border: 1px solid var(--line-strong);
		border-radius: 2px;
		padding: 2px 4px;
		background: var(--bg-soft);
		min-width: 17px;
		text-align: center;
	}

	.note {
		padding-top: 14px;
	}
	.note p {
		margin: 7px 0 0;
		font-size: 10.5px;
		line-height: 1.55;
		color: var(--dim);
	}
	.note code {
		font-family: var(--mono);
		font-size: 9.5px;
		color: var(--muted);
	}

	footer {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 10px 16px;
		border-top: 1px solid var(--line);
		background: var(--bg-soft);
	}
	.foot {
		font-family: var(--mono);
		font-size: 8.5px;
		letter-spacing: 0.08em;
		color: var(--dim);
		text-transform: uppercase;
	}

	@media (max-width: 620px) {
		.legend-grid,
		.keys,
		.gestures {
			grid-template-columns: 1fr;
		}
	}
</style>
