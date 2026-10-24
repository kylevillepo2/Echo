<script lang="ts">
	import { onMount } from 'svelte';
	import { studio } from '#lib/state/studio.svelte';
	import TopBar from '#lib/components/TopBar.svelte';
	import Sidebar from '#lib/components/Sidebar.svelte';
	import NetworkView from '#lib/components/NetworkView.svelte';
	import ThemesView from '#lib/components/ThemesView.svelte';
	import FlowsView from '#lib/components/FlowsView.svelte';
	import FlowsInspector from '#lib/components/FlowsInspector.svelte';
	import { flowsState } from '#lib/state/flows.svelte';
	import Inspector from '#lib/components/Inspector.svelte';
	import StatusBar from '#lib/components/StatusBar.svelte';
	import CommandPalette from '#lib/components/CommandPalette.svelte';
	import ConnectDialog from '#lib/components/ConnectDialog.svelte';
	import HelpDialog from '#lib/components/HelpDialog.svelte';

	onMount(() => {
		void studio.init();
	});

	function onKeydown(event: KeyboardEvent) {
		const target = event.target as HTMLElement | null;
		const typing =
			target &&
			(target.tagName === 'INPUT' ||
				target.tagName === 'TEXTAREA' ||
				target.tagName === 'SELECT' ||
				target.isContentEditable);

		if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
			event.preventDefault();
			if (studio.paletteOpen) studio.closePalette();
			else studio.openPalette();
			return;
		}

		if (event.key === 'Escape') {
			if (studio.paletteOpen) {
				studio.closePalette();
			} else if (studio.connectOpen) {
				studio.connectOpen = false;
			} else if (studio.helpOpen) {
				studio.helpOpen = false;
			} else if (studio.view === 'flows') {
				flowsState.clearSelection();
			} else {
				studio.clearSelection();
			}
			return;
		}

		if (typing || event.metaKey || event.ctrlKey || event.altKey) return;

		if (event.key === '/') {
			event.preventDefault();
			studio.openPalette();
		} else if (event.key === '1') {
			studio.setView('network');
		} else if (event.key === '2') {
			studio.setView('themes');
		} else if (event.key === '3') {
			studio.setView('flows');
		} else if (event.key.toLowerCase() === 'i') {
			studio.toggleInspector();
		}
	}
</script>

<svelte:window onkeydown={onKeydown} />

<svelte:head>
	<title>UNWRAP — app review intelligence</title>
	<meta
		name="description"
		content="A semantic map of app categories, apps and the people who use them. Reception scores, theme signals and review-level search."
	/>
</svelte:head>

<div class="shell">
	<TopBar />

	<div class="workspace">
		{#if studio.sidebarOpen}
			<Sidebar />
		{/if}

		<main class="main">
			{#if studio.view === 'flows'}
				<!-- static data: works without the backend graph -->
				<FlowsView />
			{:else if studio.loading && !studio.graph}
				<div class="boot">
					<div class="boot-mark" aria-hidden="true">U</div>
					<span class="label">Building semantic map</span>
					<div class="boot-bar"><i></i></div>
					<p>Embedding reviews · clustering themes · projecting neighbours</p>
				</div>
			{:else if !studio.graph}
				<div class="fail">
					<span class="label">Connection failed</span>
					<h1>Couldn’t load the corpus</h1>
					<p>{studio.error ?? 'The API did not return a graph payload.'}</p>
					<div class="actions">
						<button class="btn" onclick={() => (studio.connectOpen = true)}>Change source</button>
						<button class="btn is-active" onclick={() => studio.setMode('demo', '')}>
							Load demo corpus
						</button>
					</div>
				</div>
			{:else if studio.view === 'network'}
				<NetworkView />
			{:else}
				<ThemesView />
			{/if}
		</main>

		{#if studio.view === 'flows'}
			{#if studio.inspectorOpen}
				<FlowsInspector />
			{:else}
				<button class="reopen" onclick={() => (studio.inspectorOpen = true)} aria-label="Open inspector">
					<span class="label">Inspect</span>
				</button>
			{/if}
		{:else if studio.inspectorOpen && studio.graph}
			<Inspector />
		{:else if studio.graph && !studio.inspectorOpen}
			<button
				class="reopen"
				onclick={() => (studio.inspectorOpen = true)}
				aria-label="Open inspector"
			>
				<span class="label">Inspect</span>
			</button>
		{/if}
	</div>

	<StatusBar />
</div>

{#if studio.paletteOpen}
	<CommandPalette />
{/if}
{#if studio.connectOpen}
	<ConnectDialog />
{/if}
{#if studio.helpOpen}
	<HelpDialog />
{/if}

<style>
	.shell {
		height: 100dvh;
		display: flex;
		flex-direction: column;
		overflow: hidden;
	}

	.workspace {
		flex: 1;
		min-height: 0;
		display: flex;
		position: relative;
	}

	.main {
		flex: 1;
		min-width: 0;
		min-height: 0;
		display: flex;
	}

	.boot {
		flex: 1;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 12px;
		text-align: center;
	}
	.boot-mark {
		display: grid;
		place-items: center;
		width: 46px;
		height: 46px;
		background: var(--lime);
		color: #08080a;
		font-family: var(--mono);
		font-size: 22px;
		font-weight: 700;
		border-radius: 3px;
		animation: breathe 1.8s ease-in-out infinite;
	}
	.boot-bar {
		width: 210px;
		height: 3px;
		background: var(--panel-3);
		overflow: hidden;
		border-radius: 2px;
	}
	.boot-bar i {
		display: block;
		width: 40%;
		height: 100%;
		background: var(--lime);
		animation: scan 1.4s ease-in-out infinite;
	}
	.boot p {
		margin: 0;
		font-family: var(--mono);
		font-size: 8.5px;
		letter-spacing: 0.04em;
		color: var(--faint);
	}
	@keyframes breathe {
		50% {
			opacity: 0.5;
			transform: scale(0.96);
		}
	}
	@keyframes scan {
		0% {
			transform: translateX(-70px);
		}
		100% {
			transform: translateX(240px);
		}
	}

	.fail {
		flex: 1;
		display: flex;
		flex-direction: column;
		align-items: flex-start;
		justify-content: center;
		padding: 0 9vw;
	}
	.fail h1 {
		margin: 8px 0 6px;
		font-size: 27px;
		font-weight: 600;
		letter-spacing: -0.02em;
	}
	.fail p {
		margin: 0 0 16px;
		max-width: 520px;
		font-family: var(--mono);
		font-size: 10.5px;
		line-height: 1.6;
		color: var(--neg);
		word-break: break-word;
	}
	.actions {
		display: flex;
		gap: 8px;
	}

	.reopen {
		position: absolute;
		right: 0;
		top: 50%;
		transform: translateY(-50%);
		z-index: 20;
		padding: 12px 6px;
		background: var(--panel);
		border: 1px solid var(--line);
		border-right: 0;
		border-radius: 3px 0 0 3px;
		writing-mode: vertical-rl;
		color: var(--muted);
	}
	.reopen:hover {
		color: var(--text);
		border-color: var(--line-strong);
	}
</style>
