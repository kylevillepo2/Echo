<script lang="ts">
	import { studio } from '#lib/state/studio.svelte';
</script>

<header class="topbar">
	<div class="left">
		<button class="icon-btn" onclick={() => studio.toggleSidebar()} aria-label="Toggle category list">
			<svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
				<path d="M1 3h12M1 7h12M1 11h12" stroke="currentColor" stroke-width="1.3" />
			</svg>
		</button>

		<div class="brand">
			<span class="mark" aria-hidden="true">U</span>
			<div class="brand-text">
				<span class="wordmark">UNWRAP</span>
				<span class="tagline">review intelligence</span>
			</div>
		</div>
	</div>

	<nav class="views" aria-label="Workspace views">
		<button
			class:active={studio.view === 'network'}
			onclick={() => studio.setView('network')}
			aria-pressed={studio.view === 'network'}
		>
			<span class="idx">01</span> Network
		</button>
		<button
			class:active={studio.view === 'themes'}
			onclick={() => studio.setView('themes')}
			aria-pressed={studio.view === 'themes'}
		>
			<span class="idx">02</span> Themes
		</button>
		<button
			class:active={studio.view === 'flows'}
			onclick={() => studio.setView('flows')}
			aria-pressed={studio.view === 'flows'}
		>
			<span class="idx">03</span> Flows
		</button>
	</nav>

	<div class="right">
		<button class="source" onclick={() => (studio.connectOpen = true)} title="Data source">
			<span class="dot" class:live={studio.isLive}></span>
			<span class="source-mode">{studio.isLive ? 'Live' : 'Demo'}</span>
			<span class="source-corpus">{studio.meta?.label ?? 'Connecting…'}</span>
		</button>

		<button class="search" onclick={() => studio.openPalette()}>
			<svg width="12" height="12" viewBox="0 0 14 14" fill="none" aria-hidden="true">
				<circle cx="6" cy="6" r="4.4" stroke="currentColor" stroke-width="1.2" />
				<path d="M9.4 9.4 12.5 12.5" stroke="currentColor" stroke-width="1.2" />
			</svg>
			<span class="search-label">Search reviews</span>
			<kbd>⌘K</kbd>
		</button>

		<button class="icon-btn help" onclick={() => (studio.helpOpen = true)} aria-label="Help and shortcuts">
			?
		</button>
	</div>
</header>

<style>
	.topbar {
		height: var(--header-h);
		flex: none;
		display: flex;
		align-items: center;
		gap: 14px;
		padding: 0 12px 0 10px;
		border-bottom: 1px solid var(--line);
		background: var(--bg);
		position: relative;
		z-index: 30;
	}

	.left {
		display: flex;
		align-items: center;
		gap: 10px;
		min-width: 0;
	}

	.icon-btn {
		display: grid;
		place-items: center;
		width: 28px;
		height: 28px;
		border: 1px solid transparent;
		border-radius: 2px;
		color: var(--muted);
		font-family: var(--mono);
		font-size: 12px;
		transition:
			color var(--fast),
			border-color var(--fast),
			background var(--fast);
	}
	.icon-btn:hover {
		color: var(--text);
		border-color: var(--line-strong);
		background: var(--panel-2);
	}

	.brand {
		display: flex;
		align-items: center;
		gap: 8px;
	}

	.mark {
		display: grid;
		place-items: center;
		width: 26px;
		height: 26px;
		background: var(--lime);
		color: #08080a;
		font-family: var(--mono);
		font-weight: 700;
		font-size: 14px;
		border-radius: 2px;
		letter-spacing: -0.04em;
	}

	.brand-text {
		display: flex;
		flex-direction: column;
		line-height: 1;
	}
	.wordmark {
		font-family: var(--mono);
		font-weight: 700;
		font-size: 13px;
		letter-spacing: 0.14em;
	}
	.tagline {
		font-family: var(--mono);
		font-size: 8px;
		letter-spacing: 0.16em;
		text-transform: uppercase;
		color: var(--dim);
		margin-top: 3px;
	}

	.views {
		display: flex;
		align-items: center;
		gap: 2px;
		padding: 2px;
		border: 1px solid var(--line);
		border-radius: 2px;
		background: var(--bg-soft);
		margin-left: 4px;
	}
	.views button {
		display: flex;
		align-items: center;
		gap: 7px;
		height: 26px;
		padding: 0 11px;
		border-radius: 1px;
		font-family: var(--mono);
		font-size: 10.5px;
		font-weight: 500;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: var(--muted);
		transition:
			background var(--fast),
			color var(--fast);
	}
	.views button:hover {
		color: var(--text);
	}
	.views button.active {
		background: var(--panel-3);
		color: var(--text);
		box-shadow: inset 0 -1px 0 var(--lime);
	}
	.idx {
		font-size: 8.5px;
		color: var(--dim);
	}
	.views button.active .idx {
		color: var(--lime);
	}

	.right {
		margin-left: auto;
		display: flex;
		align-items: center;
		gap: 8px;
		min-width: 0;
	}

	.source {
		display: flex;
		align-items: center;
		gap: 7px;
		height: 28px;
		padding: 0 9px;
		border: 1px solid var(--line);
		border-radius: 2px;
		background: var(--bg-soft);
		color: var(--muted);
		min-width: 0;
		transition: border-color var(--fast);
	}
	.source:hover {
		border-color: var(--line-strong);
	}
	.dot {
		width: 5px;
		height: 5px;
		border-radius: 50%;
		background: var(--amber);
		flex: none;
	}
	.dot.live {
		background: var(--pos);
		box-shadow: 0 0 0 3px color-mix(in srgb, var(--pos) 16%, transparent);
	}
	.source-mode {
		font-family: var(--mono);
		font-size: 9px;
		letter-spacing: 0.12em;
		text-transform: uppercase;
		color: var(--text-2);
	}
	.source-corpus {
		font-family: var(--mono);
		font-size: 9px;
		color: var(--dim);
		max-width: 190px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		padding-left: 7px;
		border-left: 1px solid var(--line);
	}

	.search {
		display: flex;
		align-items: center;
		gap: 7px;
		height: 28px;
		width: 208px;
		padding: 0 8px;
		border: 1px solid var(--line);
		border-radius: 2px;
		background: var(--bg-soft);
		color: var(--dim);
		text-align: left;
		transition: border-color var(--fast);
	}
	.search:hover {
		border-color: var(--line-bright);
	}
	.search-label {
		font-family: var(--mono);
		font-size: 10px;
		color: var(--dim);
		flex: 1;
	}
	.search kbd {
		font-family: var(--mono);
		font-size: 8.5px;
		color: var(--muted);
		border: 1px solid var(--line);
		border-radius: 2px;
		padding: 1px 4px;
		background: var(--panel);
	}
	.help {
		border-color: var(--line);
	}

	@media (max-width: 1280px) {
		.source-corpus {
			display: none;
		}
	}
	@media (max-width: 1024px) {
		.tagline {
			display: none;
		}
		.search {
			width: 34px;
			justify-content: center;
		}
		.search-label,
		.search kbd {
			display: none;
		}
	}
	@media (max-width: 720px) {
		.views button {
			padding: 0 8px;
		}
		.idx {
			display: none;
		}
		.source-mode {
			display: none;
		}
		.source {
			width: 26px;
			justify-content: center;
			padding: 0;
		}
		.mark {
			width: 24px;
			height: 24px;
		}
		.wordmark {
			font-size: 11px;
		}
	}
</style>
