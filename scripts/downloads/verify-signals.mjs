import { createServer } from 'vite';

const server = await createServer({
	root: process.cwd(),
	server: { middlewareMode: true },
	appType: 'custom',
	logLevel: 'error'
});

try {
	const mod = await server.ssrLoadModule('/src/lib/api/mock.ts');
	const api = new mod.MockApi();
	const t0 = Date.now();
	const graph = await api.getGraph();
	const ms = Date.now() - t0;
	console.log(`graph in ${ms}ms · apps ${graph.apps.length} · themes ${graph.themes.length}`);
	const withSignals = graph.apps.filter((a) => a.signals);
	console.log(`apps with signals: ${withSignals.length}`);
	console.log('\nspotify signals:');
	const spotify = graph.apps.find((a) => a.id === 'spotify');
	console.log(JSON.stringify({ volume: spotify.signals.volume, sentiment: spotify.signals.sentiment, drivers: spotify.signals.drivers }, null, 2));
	console.log('\ntheme impacts:');
	for (const theme of graph.themes.slice(0, 8)) {
		console.log(theme.kind.padEnd(8), theme.label.padEnd(28), theme.impact);
	}
	console.log('\nall driver signs:');
	for (const app of withSignals.slice(0, 12)) {
		const bad = app.signals.drivers.filter((d) => (d.kind === 'positive' ? d.r < 0 : d.r > 0));
		console.log(app.id.padEnd(18), 'vol', app.signals.volume.r, 'sent', app.signals.sentiment.r, 'drivers', app.signals.drivers.map((d) => `${d.label}:${d.r}@${d.lag}`).join(' | '), bad.length ? `BAD ${bad.length}` : '');
	}
} finally {
	await server.close();
}
