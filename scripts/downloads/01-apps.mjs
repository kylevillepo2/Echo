/* Extract the 60 demo apps from src/lib/api/mock.ts into apps.json + apps.csv */
import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, '../..');
const src = readFileSync(resolve(root, 'src/lib/api/mock.ts'), 'utf8');

const catRe = /\{\s*id: '([^']+)',\s*name: '([^']+)',\s*blurb:/g;
const categories = [];
let m;
while ((m = catRe.exec(src))) {
	categories.push({ id: m[1], name: m[2], start: m.index, end: src.length });
}
for (let i = 0; i < categories.length; i++) {
	if (i < categories.length - 1) categories[i].end = categories[i + 1].start;
}

const appRe =
	/id: '([a-z0-9-]+)',\s*name: '([^']+)',\s*volume: ([\d_]+),\s*rating: ([\d.]+),\s*subcategory: '([^']+)',(?:\s*platform: '(\w+)',)?/g;

const apps = [];
for (const category of categories) {
	const block = src.slice(category.start, category.end);
	let a;
	appRe.lastIndex = 0;
	while ((a = appRe.exec(block))) {
		apps.push({
			id: a[1],
			name: a[2],
			categoryId: category.id,
			categoryName: category.name,
			platform: a[6] ?? 'both',
			subcategory: a[5],
			volume: Number(a[3].replace(/_/g, '')),
			rating: Number(a[4]),
			iosTrackId: '',
			androidPackage: '',
			notes: ''
		});
	}
}

writeFileSync(resolve(here, 'apps.json'), JSON.stringify(apps, null, 2) + '\n');

const csv = [
	'app_id,name,platform,volume,ios_track_id,android_package,notes',
	...apps.map((a) =>
		[a.id, a.name, a.platform, a.volume, '', '', '']
			.map((v) => (/[",]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : v))
			.join(',')
	)
].join('\n');
writeFileSync(resolve(here, 'apps.csv'), csv + '\n');

console.log(`${apps.length} apps across ${categories.length} categories → apps.json, apps.csv`);
