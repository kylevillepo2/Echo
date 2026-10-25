/* Refresh local app artwork from mapped App Store IDs and competitor brand favicons.
   No requests to third-party image services are needed while using the website. */
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const root = new URL('../', import.meta.url);
const mapping = JSON.parse(readFileSync(new URL('scripts/downloads/mapping.json', root), 'utf8'));
const directory = new URL('static/logos/', root);
mkdirSync(directory, { recursive: true });

const domains = {
	chai: 'chai-research.com', polybuzz: 'polybuzz.ai', tiktok: 'tiktok.com', talkie: 'talkie-ai.com',
	'janitor-ai': 'janitorai.com', facebook: 'facebook.com', 'facebook-dating': 'facebook.com',
	'apple-music': 'music.apple.com', 'youtube-music': 'music.youtube.com', youtube: 'youtube.com',
	pandora: 'pandora.com', 'amazon-music': 'music.amazon.com', musi: 'feelthemusi.com',
	kindle: 'amazon.com', babbel: 'babbel.com', 'rosetta-stone': 'rosettastone.com', busuu: 'busuu.com',
	ao3: 'archiveofourown.org', netflix: 'netflix.com', hulu: 'hulu.com', 'fire-tv': 'amazon.com',
	'pluto-tv': 'pluto.tv', amazon: 'amazon.com', aliexpress: 'aliexpress.com', shein: 'shein.com',
	vinted: 'vinted.com', poshmark: 'poshmark.com', mercari: 'mercari.com', zelle: 'zellepay.com',
	chase: 'chase.com', 'wells-fargo': 'wellsfargo.com', fidelity: 'fidelity.com',
	'charles-schwab': 'schwab.com', netspend: 'netspend.com', cronometer: 'cronometer.com',
	'us-bank': 'usbank.com', 'td-bank': 'td.com', sofi: 'sofi.com', revolut: 'revolut.com',
	monzo: 'monzo.com', current: 'current.com', discover: 'discover.com', 'american-express': 'americanexpress.com',
	'lose-it': 'loseit.com', fitbit: 'fitbit.com', ww: 'weightwatchers.com', stardust: 'stardust.app',
	'google-maps': 'maps.google.com', 'alight-motion': 'alightmotion.com', canva: 'canva.com',
	inshot: 'inshot.com', photoshop: 'adobe.com', kinemaster: 'kinemaster.com', vn: 'vlognow.me',
	'plenty-of-fish': 'pof.com', okcupid: 'okcupid.com', eharmony: 'eharmony.com',
	feeld: 'feeld.co', 'coffee-meets-bagel': 'coffeemeetsbagel.com', lyft: 'lyft.com',
	'uber-eats': 'ubereats.com', grubhub: 'grubhub.com', bolt: 'bolt.eu', vrbo: 'vrbo.com',
	indrive: 'indrive.com', lichess: 'lichess.org', beatstar: 'beatstar.com',
	ziprecruiter: 'ziprecruiter.com', 'microsoft-teams': 'teams.microsoft.com',
	'google-meet': 'meet.google.com', snagajob: 'snagajob.com', monster: 'monster.com',
	skype: 'skype.com', chrome: 'google.com', firefox: 'firefox.com', accuweather: 'accuweather.com',
	safari: 'apple.com', duckduckgo: 'duckduckgo.com', 'apple-weather': 'weather.apple.com'
};

// Verified store IDs for frequently shown competitors; never accept an unrelated lookup result.
const extraStoreIds = {
	'apple-music': [1108187390, 'Apple Music'], 'youtube-music': [1017492454, 'YouTube Music'],
	youtube: [544007664, 'YouTube'], pandora: [284035177, 'Pandora'], 'amazon-music': [510855668, 'Amazon Music'],
	kindle: [302584613, 'Kindle'], tiktok: [835599320, 'TikTok'], facebook: [284882215, 'Facebook'],
	'facebook-dating': [284882215, 'Facebook'], netflix: [363590051, 'Netflix'], hulu: [376510438, 'Hulu'],
	'pluto-tv': [751712884, 'Pluto'], aliexpress: [436672029, 'AliExpress'], shein: [878577184, 'SHEIN'],
	vinted: [632064380, 'Vinted'], poshmark: [470412147, 'Poshmark'], mercari: [896130944, 'Mercari'],
	chase: [298867247, 'Chase'], 'wells-fargo': [311548709, 'Wells Fargo'], fidelity: [348177453, 'Fidelity'],
	'charles-schwab': [407358186, 'Schwab'], 'us-bank': [458734623, 'Bank'], 'td-bank': [382107453, 'TD'],
	cronometer: [1145935738, 'Cronometer'], 'lose-it': [297368629, 'Lose It'], fitbit: [462638897, 'Fitbit'],
	'google-maps': [585027354, 'Google Maps'], canva: [897446215, 'Canva'], inshot: [997362197, 'InShot'],
	kinemaster: [1223932558, 'KineMaster'], vn: [1343581380, 'VN'], snapseed: [439438619, 'Snapseed'],
	okcupid: [338701294, 'OkCupid'], 'plenty-of-fish': [389638243, 'Fish'], feeld: [887914690, 'Feeld'],
	lyft: [529379082, 'Lyft'], 'uber-eats': [1058959277, 'Uber Eats'], grubhub: [302920553, 'Grubhub'],
	vrbo: [334768014, 'Vrbo'], chrome: [535886823, 'Chrome'], firefox: [989804926, 'Firefox'],
	accuweather: [300048137, 'AccuWeather'], duckduckgo: [663592361, 'DuckDuckGo'],
	'microsoft-teams': [1113153706, 'Microsoft Teams'], 'google-meet': [1013231476, 'Google Meet'],
	ziprecruiter: [541933937, 'ZipRecruiter']
};

const ids = [...new Set([...mapping.map((app) => app.ios.trackId), ...Object.values(extraStoreIds).map(([id]) => id)])];
const response = await fetch(`https://itunes.apple.com/lookup?id=${ids.join(',')}&country=us`, { signal: AbortSignal.timeout(30000) });
if (!response.ok) throw new Error(`App Store artwork lookup failed: ${response.status}`);
const lookup = await response.json();
const records = new Map(lookup.results.map((app) => [app.trackId, app]));
const tasks = mapping.map((app) => {
	const record = records.get(app.ios.trackId);
	if (!record?.artworkUrl100) throw new Error(`No verified App Store artwork for ${app.name}`);
	return { id: app.id, source: record.artworkUrl100, kind: 'app-store', name: record.trackName, trackId: record.trackId };
});
const normalize = (value) => value.toLowerCase().replace(/[^a-z0-9]/g, '');
for (const [id, [trackId, expected]] of Object.entries(extraStoreIds)) {
	const record = records.get(trackId);
	if (record?.artworkUrl100 && normalize(record.trackName).includes(normalize(expected))) tasks.push({ id, source: record.artworkUrl100, kind: 'app-store', name: record.trackName, trackId });
}
for (const [id, domain] of Object.entries(domains)) {
	if (!tasks.some((task) => task.id === id)) tasks.push({ id, source: `https://www.google.com/s2/favicons?domain=${domain}&sz=128`, kind: 'brand-favicon', domain });
}

const manifest = {};
const sources = {};
let cursor = 0;
const failures = [];
await Promise.all(Array.from({ length: 6 }, async () => {
	while (cursor < tasks.length) {
		const task = tasks[cursor++];
		try {
			const response = await fetch(task.source, { signal: AbortSignal.timeout(20000) });
			const type = response.headers.get('content-type') ?? '';
			if (!response.ok || !type.startsWith('image/')) throw new Error(`HTTP ${response.status}, ${type}`);
			const extension = type.includes('png') ? 'png' : type.includes('svg') ? 'svg' : 'jpg';
			const bytes = Buffer.from(await response.arrayBuffer());
			if (bytes.length < 100) throw new Error('Empty artwork');
			const filename = `${task.id}.${extension}`;
			const path = new URL(filename, directory);
			if (!existsSync(path) || !readFileSync(path).equals(bytes)) writeFileSync(path, bytes);
			manifest[task.id] = `logos/${filename}`;
			sources[task.id] = task;
		} catch (error) { failures.push(`${task.id}: ${error.message}`); }
	}
}));
const sorted = Object.fromEntries(Object.entries(manifest).sort(([a], [b]) => a.localeCompare(b)));
const saveJson = (path, value) => { const content = `${JSON.stringify(value, null, 2)}\n`; if (!existsSync(path) || readFileSync(path, 'utf8') !== content) writeFileSync(path, content); };
saveJson(new URL('src/lib/data/app-logos.json', root), sorted);
saveJson(new URL('sources.json', directory), Object.fromEntries(Object.entries(sources).sort(([a], [b]) => a.localeCompare(b))));
console.log(`Saved ${Object.keys(manifest).length} local logos in ${fileURLToPath(directory)}`);
if (failures.length) console.warn(failures.join('\n'));
if (mapping.some((app) => !manifest[app.id])) process.exitCode = 1;
