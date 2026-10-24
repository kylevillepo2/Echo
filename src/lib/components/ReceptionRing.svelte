<script lang="ts">
	import { receptionColor, receptionLabel } from '#lib/utils/palette';

	let {
		score,
		size = 104,
		stroke = 6,
		label = true
	}: { score: number; size?: number; stroke?: number; label?: boolean } = $props();

	const radius = $derived(size / 2 - stroke);
	const circumference = $derived(2 * Math.PI * radius);
	const dash = $derived((Math.max(0, Math.min(100, score)) / 100) * circumference);
	const color = $derived(receptionColor(score));
	const textSize = $derived(size * 0.28);
</script>

<svg
	width={size}
	height={size}
	viewBox="0 0 {size} {size}"
	role="img"
	aria-label="Reception score {score} out of 100, {receptionLabel(score)}"
>
	<circle
		cx={size / 2}
		cy={size / 2}
		r={radius}
		fill="none"
		stroke="var(--panel-3)"
		stroke-width={stroke}
	/>
	<circle
		cx={size / 2}
		cy={size / 2}
		r={radius}
		fill="none"
		stroke={color}
		stroke-width={stroke}
		stroke-linecap="round"
		stroke-dasharray={`${dash} ${circumference - dash}`}
		transform="rotate(-90 {size / 2} {size / 2})"
		class="arc"
	/>
	<text
		x={size / 2}
		y={label ? size / 2 + 2 : size / 2 + textSize * 0.36}
		text-anchor="middle"
		fill="var(--text)"
		font-family="var(--mono)"
		font-size={textSize}
		font-weight="600"
		letter-spacing="-1"
	>
		{Math.round(score)}
	</text>
	{#if label}
		<text
			x={size / 2}
			y={size / 2 + textSize * 0.95}
			text-anchor="middle"
			fill={color}
			font-family="var(--mono)"
			font-size={size * 0.085}
			letter-spacing="1.4"
		>
			{receptionLabel(score).toUpperCase()}
		</text>
	{/if}
</svg>

<style>
	.arc {
		transition: stroke-dasharray 700ms cubic-bezier(0.22, 1, 0.36, 1);
	}
</style>
