/* ============================================================
   Deterministic demo dataset.

   Mirrors the real corpus: 60 apps across 13 category clusters,
   5.5M reviews in the index and a sampled review stream for the
   inspector/search.

   The graph is organised by category, never by publisher. Each
   category is a clickable cluster of apps.

   Replace this with your API by switching to "Live" in the
   connect dialog (see src/lib/api/http.ts).
   ============================================================ */

import type {
	AppNode,
	AppSignals,
	Category,
	CorrelationSignal,
	GraphPayload,
	Platform,
	Review,
	SearchHit,
	SearchOptions,
	SignalWeek,
	Theme,
	ThemeImpact,
	TrendPoint,
	UnwrapApi
} from './types';
import { accentFor, sentimentFromStars } from '#lib/utils/palette';
import { downloadStats } from '#lib/data/downloads';
import { mergeImpact, signal } from '#lib/utils/correlation';

/* ----------------------------- rng ----------------------------- */

function mulberry32(seed: number) {
	return function rand() {
		seed |= 0;
		seed = (seed + 0x6d2b79f5) | 0;
		let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
		t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
		return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
	};
}

type Rand = () => number;

function choose<T>(rng: Rand, arr: readonly T[]): T {
	return arr[Math.floor(rng() * arr.length)];
}

function chooseWeighted<T>(rng: Rand, arr: readonly T[], weight: (item: T) => number): T {
	const total = arr.reduce((sum, item) => sum + Math.max(0, weight(item)), 0);
	let r = rng() * total;
	for (const item of arr) {
		r -= Math.max(0, weight(item));
		if (r <= 0) return item;
	}
	return arr[arr.length - 1];
}

/* --------------------------- themes ---------------------------- */

interface ThemeSpec {
	id: string;
	label: string;
	kind: 'positive' | 'negative';
	phrases: string[];
}

const POSITIVE_THEMES: ThemeSpec[] = [
	{
		id: 'community',
		label: 'Community',
		kind: 'positive',
		phrases: [
			'The community here is the reason I stay.',
			'I have found my people in this app.',
			'Comments and groups are genuinely helpful.'
		]
	},
	{
		id: 'content',
		label: 'Content library',
		kind: 'positive',
		phrases: [
			'There is always something new to browse.',
			'The library is huge and well organised.',
			'I never run out of things to watch, read or listen to.'
		]
	},
	{
		id: 'design',
		label: 'Design',
		kind: 'positive',
		phrases: [
			'The interface is clean and easy to navigate.',
			'Everything is exactly where I expect it to be.',
			'It looks great without getting in the way.'
		]
	},
	{
		id: 'features',
		label: 'Features',
		kind: 'positive',
		phrases: [
			'There are more features here than I expected.',
			'It does the small things other apps forget.',
			'Every tool I need is built in.'
		]
	},
	{
		id: 'speed',
		label: 'Speed',
		kind: 'positive',
		phrases: [
			'It opens instantly and never keeps me waiting.',
			'Everything responds the moment I tap.',
			'Fast, even on a bad connection.'
		]
	},
	{
		id: 'reliability',
		label: 'Reliability',
		kind: 'positive',
		phrases: [
			'It works every single time I open it.',
			'I have never had it fail on me.',
			'Consistent and dependable.'
		]
	},
	{
		id: 'value',
		label: 'Value',
		kind: 'positive',
		phrases: [
			'I get a lot for what I pay.',
			'Worth every penny of the subscription.',
			'The value here is hard to beat.'
		]
	},
	{
		id: 'free',
		label: 'Free tier',
		kind: 'positive',
		phrases: [
			'The free version covers everything I need.',
			'No paywall blocking the basics.',
			'Rare to find this much without a subscription.'
		]
	},
	{
		id: 'savings',
		label: 'Savings & rewards',
		kind: 'positive',
		phrases: [
			'I have saved real money using this.',
			'The rewards add up faster than I expected.',
			'Found deals here I could not get anywhere else.'
		]
	},
	{
		id: 'personalization',
		label: 'Recommendations',
		kind: 'positive',
		phrases: [
			'The recommendations are scarily accurate.',
			'It learns what I like and surfaces more of it.',
			'My feed feels made for me.'
		]
	},
	{
		id: 'ai',
		label: 'AI features',
		kind: 'positive',
		phrases: [
			'The AI helper actually saves me time.',
			'The smart suggestions are genuinely useful.',
			'AI features feel polished, not bolted on.'
		]
	},
	{
		id: 'security',
		label: 'Security',
		kind: 'positive',
		phrases: [
			'I feel safe entering my details here.',
			'The security checks are reassuring without being annoying.',
			'Fraud alerts have caught things before I did.'
		]
	},
	{
		id: 'accuracy',
		label: 'Accuracy',
		kind: 'positive',
		phrases: [
			'The information is accurate and up to date.',
			'I trust what it shows me.',
			'Details match reality every time.'
		]
	},
	{
		id: 'support',
		label: 'Support',
		kind: 'positive',
		phrases: [
			'Support sorted my issue in one chat.',
			'A real person replied within a day.',
			'The team actually follows up.'
		]
	}
];

const NEGATIVE_THEMES: ThemeSpec[] = [
	{
		id: 'moderation',
		label: 'Moderation',
		kind: 'negative',
		phrases: [
			'Reporting does nothing — the same accounts stay up.',
			'The feed is full of spam and scams.',
			'Moderation feels nonexistent.'
		]
	},
	{
		id: 'ads',
		label: 'Ads',
		kind: 'negative',
		phrases: [
			'There are ads everywhere now.',
			'Every third post is sponsored.',
			'The ads make it hard to use.'
		]
	},
	{
		id: 'notifications',
		label: 'Notifications',
		kind: 'negative',
		phrases: [
			'It will not stop sending notifications.',
			'Notifications are pure engagement bait.',
			'Alerts arrive at the worst times.'
		]
	},
	{
		id: 'bugs',
		label: 'Bugs',
		kind: 'negative',
		phrases: [
			'Basic things are broken in the latest build.',
			'Buttons do not respond on the first tap.',
			'Small bugs pile up with every update.'
		]
	},
	{
		id: 'crashes',
		label: 'Crashes',
		kind: 'negative',
		phrases: [
			'It crashes every time I open it.',
			'Force closes in the middle of a task.',
			'Constant crashes make it unusable.'
		]
	},
	{
		id: 'content-quality',
		label: 'Content quality',
		kind: 'negative',
		phrases: [
			'The quality of content has dropped sharply.',
			'Half the library feels like filler.',
			'Recommendations keep getting worse.'
		]
	},
	{
		id: 'subscription',
		label: 'Subscription pressure',
		kind: 'negative',
		phrases: [
			'Everything useful is behind a paywall.',
			'The subscription is pushed on every screen.',
			'Free features keep moving behind a paywall.'
		]
	},
	{
		id: 'pricing',
		label: 'Pricing',
		kind: 'negative',
		phrases: [
			'Prices change depending on the user.',
			'The price keeps creeping up.',
			'Too expensive for what you get.'
		]
	},
	{
		id: 'fees',
		label: 'Fees',
		kind: 'negative',
		phrases: [
			'The fees are ridiculous.',
			'Hidden charges show up at checkout.',
			'A small transaction turned into a big fee.'
		]
	},
	{
		id: 'delivery',
		label: 'Delivery',
		kind: 'negative',
		phrases: [
			'Delivery estimates are never right.',
			'Orders arrive late or not at all.',
			'Tracking stops updating for hours.'
		]
	},
	{
		id: 'spam',
		label: 'Spam & fakes',
		kind: 'negative',
		phrases: [
			'Half the listings are spam.',
			'Fake accounts are everywhere.',
			'Search results are full of scams.'
		]
	},
	{
		id: 'support-bad',
		label: 'Support',
		kind: 'negative',
		phrases: [
			'Support is impossible to reach.',
			'No way to contact a human.',
			'Reported the same issue three times with no reply.'
		]
	},
	{
		id: 'account',
		label: 'Account lockout',
		kind: 'negative',
		phrases: [
			'My account was locked for no reason.',
			'Signing in suddenly stopped working.',
			'Verification wiped my progress.'
		]
	},
	{
		id: 'login',
		label: 'Sign-in problems',
		kind: 'negative',
		phrases: [
			'I keep getting signed out.',
			'The login loop never ends.',
			'Two-factor codes never arrive.'
		]
	},
	{
		id: 'verification',
		label: 'Verification',
		kind: 'negative',
		phrases: [
			'Verification is an endless loop.',
			'It asks for the same documents again and again.',
			'Identity checks fail for no reason.'
		]
	},
	{
		id: 'update',
		label: 'Bad updates',
		kind: 'negative',
		phrases: [
			'The latest update made it worse.',
			'Every update removes something I used.',
			'The redesign buried every setting.'
		]
	},
	{
		id: 'battery',
		label: 'Battery drain',
		kind: 'negative',
		phrases: [
			'It drains my battery even when idle.',
			'My phone gets hot within minutes.',
			'Battery usage is absurd for an app like this.'
		]
	},
	{
		id: 'wait',
		label: 'Wait times',
		kind: 'negative',
		phrases: [
			'Wait times are out of control.',
			'I have been on hold for hours.',
			'Support takes days to respond.'
		]
	},
	{
		id: 'tracking',
		label: 'Tracking',
		kind: 'negative',
		phrases: [
			'It tracks more than it should.',
			'The privacy settings are misleading.',
			'Data collection is opt-out, not opt-in.'
		]
	},
	{
		id: 'inaccurate',
		label: 'Inaccurate data',
		kind: 'negative',
		phrases: [
			'The data is often wrong or out of date.',
			'Forecasts and figures do not match reality.',
			'It confidently shows information that is simply incorrect.'
		]
	},
	{
		id: 'search-quality',
		label: 'Search quality',
		kind: 'negative',
		phrases: [
			'Search results are irrelevant and full of noise.',
			'Search is noticeably worse than it used to be.',
			'Finding anything specific takes far too long.'
		]
	}
];

const THEME_BY_ID = new Map<string, ThemeSpec>(
	[...POSITIVE_THEMES, ...NEGATIVE_THEMES].map((t) => [t.id, t])
);

/* --------------------------- corpus ---------------------------- */

interface AppSeed {
	id: string;
	name: string;
	volume: number;
	rating: number;
	subcategory: string;
	platform?: Platform;
	loves: string[];
	hurts: string[];
}

interface CategorySpec {
	id: string;
	name: string;
	blurb: string;
	apps: AppSeed[];
}

/**
 * 60 apps from the processed review export, grouped into semantic
 * clusters. Volumes are the real review counts from the corpus.
 */
const CATEGORY_SPECS: CategorySpec[] = [
	{
		id: 'social',
		name: 'Social & Community',
		blurb: 'Feeds, forums and creator communities',
		apps: [
			{
				id: 'discord',
				name: 'Discord',
				volume: 98_776,
				rating: 4.4,
				subcategory: 'Chat & communities',
				loves: ['community', 'features', 'speed'],
				hurts: ['crashes', 'notifications', 'moderation']
			},
			{
				id: 'reddit',
				name: 'Reddit',
				volume: 112_848,
				rating: 4.3,
				subcategory: 'Forums',
				loves: ['community', 'content', 'design'],
				hurts: ['moderation', 'ads', 'bugs']
			},
			{
				id: 'pinterest',
				name: 'Pinterest',
				volume: 131_488,
				rating: 4.3,
				subcategory: 'Visual discovery',
				loves: ['content', 'personalization', 'design'],
				hurts: ['ads', 'search-quality', 'notifications']
			},
			{
				id: 'lemon8',
				name: 'Lemon8',
				volume: 20_613,
				rating: 4.4,
				subcategory: 'Lifestyle feed',
				loves: ['content', 'design', 'personalization'],
				hurts: ['content-quality', 'ads', 'bugs']
			},
			{
				id: 'character-ai',
				name: 'Character.ai',
				volume: 237_573,
				rating: 4.4,
				subcategory: 'AI companions',
				loves: ['ai', 'features', 'personalization'],
				hurts: ['subscription', 'crashes', 'moderation']
			}
		]
	},
	{
		id: 'music',
		name: 'Music',
		blurb: 'Music streaming, discovery and podcasts',
		apps: [
			{
				id: 'spotify',
				name: 'Spotify',
				volume: 185_745,
				rating: 4.4,
				subcategory: 'Music streaming',
				loves: ['content', 'personalization', 'design'],
				hurts: ['subscription', 'ads', 'bugs']
			},
			{
				id: 'soundcloud',
				name: 'SoundCloud',
				volume: 43_422,
				rating: 4.4,
				subcategory: 'Music & podcasts',
				loves: ['content', 'community', 'free'],
				hurts: ['ads', 'subscription', 'bugs']
			},
			{
				id: 'audiomack',
				name: 'Audiomack',
				volume: 299_802,
				rating: 4.5,
				subcategory: 'Music streaming',
				loves: ['content', 'free', 'design'],
				hurts: ['ads', 'bugs', 'content-quality']
			}
		]
	},
	{
		id: 'tv',
		name: 'TV',
		blurb: 'TV, films, anime and video streaming',
		apps: [
			{
				id: 'crunchyroll',
				name: 'Crunchyroll',
				volume: 92_207,
				rating: 4.2,
				subcategory: 'Anime streaming',
				loves: ['content', 'value', 'features'],
				hurts: ['ads', 'subscription', 'bugs']
			},
			{
				id: 'tubi',
				name: 'Tubi',
				volume: 50_913,
				rating: 4.5,
				subcategory: 'Free streaming',
				loves: ['free', 'content', 'design'],
				hurts: ['ads', 'content-quality', 'bugs']
			},
			{
				id: 'roku',
				name: 'Roku',
				volume: 44_434,
				rating: 4.5,
				subcategory: 'TV streaming',
				loves: ['content', 'design', 'features'],
				hurts: ['crashes', 'ads', 'update']
			}
		]
	},
	{
		id: 'learning',
		name: 'Learning & Reading',
		blurb: 'Books, study and language learning',
		apps: [
			{
				id: 'audible',
				name: 'Audible',
				volume: 46_977,
				rating: 4.5,
				subcategory: 'Audiobooks',
				loves: ['content', 'value', 'features'],
				hurts: ['subscription', 'pricing', 'bugs']
			},
			{
				id: 'duolingo',
				name: 'Duolingo',
				volume: 599_932,
				rating: 4.7,
				subcategory: 'Language learning',
				loves: ['content', 'design', 'personalization'],
				hurts: ['notifications', 'subscription', 'bugs']
			},
			{
				id: 'libby',
				name: 'Libby',
				volume: 43_214,
				rating: 4.7,
				subcategory: 'Library lending',
				loves: ['free', 'content', 'design'],
				hurts: ['login', 'bugs', 'search-quality']
			},
			{
				id: 'hoopla',
				name: 'Hoopla',
				volume: 20_445,
				rating: 4.4,
				subcategory: 'Library media',
				loves: ['free', 'content', 'features'],
				hurts: ['login', 'bugs', 'content-quality']
			},
			{
				id: 'wattpad',
				name: 'Wattpad',
				volume: 34_724,
				rating: 4.4,
				subcategory: 'Stories & fanfiction',
				loves: ['content', 'community', 'personalization'],
				hurts: ['ads', 'subscription', 'bugs']
			}
		]
	},
	{
		id: 'shopping',
		name: 'Shopping & Rewards',
		blurb: 'Marketplaces, resale and cashback',
		apps: [
			{
				id: 'temu',
				name: 'Temu',
				volume: 202_585,
				rating: 4.6,
				subcategory: 'Marketplace',
				loves: ['value', 'savings', 'content'],
				hurts: ['delivery', 'pricing', 'spam']
			},
			{
				id: 'ebay',
				name: 'eBay',
				volume: 82_712,
				rating: 4.4,
				subcategory: 'Marketplace',
				loves: ['value', 'content', 'features'],
				hurts: ['fees', 'spam', 'support-bad']
			},
			{
				id: 'shopify',
				name: 'Shopify',
				volume: 50_718,
				rating: 4.2,
				subcategory: 'Store management',
				loves: ['features', 'design', 'reliability'],
				hurts: ['pricing', 'bugs', 'support-bad']
			},
			{
				id: 'depop',
				name: 'Depop',
				volume: 22_600,
				rating: 4.3,
				subcategory: 'Resale',
				loves: ['content', 'community', 'design'],
				hurts: ['fees', 'spam', 'support-bad']
			},
			{
				id: 'fetch',
				name: 'Fetch',
				volume: 87_942,
				rating: 4.2,
				subcategory: 'Rewards',
				platform: 'android',
				loves: ['savings', 'free', 'design'],
				hurts: ['bugs', 'account', 'support-bad']
			},
			{
				id: 'sweatcoin',
				name: 'Sweatcoin',
				volume: 42_544,
				rating: 4.3,
				subcategory: 'Move-to-earn',
				platform: 'android',
				loves: ['savings', 'free', 'content'],
				hurts: ['bugs', 'account', 'ads']
			}
		]
	},
	{
		id: 'finance',
		name: 'Finance & Banking',
		blurb: 'Banking, payments and investing',
		apps: [
			{
				id: 'cash-app',
				name: 'Cash App',
				volume: 105_300,
				rating: 4.5,
				subcategory: 'Payments',
				loves: ['speed', 'design', 'free'],
				hurts: ['fees', 'login', 'support-bad']
			},
			{
				id: 'venmo',
				name: 'Venmo',
				volume: 78_915,
				rating: 4.5,
				subcategory: 'Payments',
				loves: ['speed', 'design', 'free'],
				hurts: ['fees', 'support-bad', 'verification']
			},
			{
				id: 'paypal',
				name: 'PayPal',
				volume: 87_155,
				rating: 4.2,
				subcategory: 'Payments',
				loves: ['security', 'features', 'reliability'],
				hurts: ['fees', 'account', 'support-bad']
			},
			{
				id: 'chime',
				name: 'Chime',
				volume: 72_463,
				rating: 4.4,
				subcategory: 'Banking',
				loves: ['free', 'design', 'speed'],
				hurts: ['account', 'support-bad', 'verification']
			},
			{
				id: 'capital-one',
				name: 'Capital One Mobile',
				volume: 69_369,
				rating: 4.7,
				subcategory: 'Banking',
				loves: ['security', 'features', 'design'],
				hurts: ['login', 'bugs', 'update']
			},
			{
				id: 'bofa',
				name: 'Bank of America Mobile Banking',
				volume: 49_355,
				rating: 4.6,
				subcategory: 'Banking',
				loves: ['security', 'features', 'reliability'],
				hurts: ['login', 'crashes', 'update']
			},
			{
				id: 'coinbase',
				name: 'Coinbase',
				volume: 40_371,
				rating: 4.3,
				subcategory: 'Crypto',
				loves: ['features', 'security', 'design'],
				hurts: ['fees', 'verification', 'support-bad']
			},
			{
				id: 'dave',
				name: 'Dave',
				volume: 25_307,
				rating: 4.4,
				subcategory: 'Cash advance',
				platform: 'android',
				loves: ['free', 'speed', 'design'],
				hurts: ['fees', 'account', 'support-bad']
			},
			{
				id: 'credit-karma',
				name: 'Intuit Credit Karma',
				volume: 20_682,
				rating: 4.6,
				subcategory: 'Credit scores',
				loves: ['free', 'features', 'design'],
				hurts: ['ads', 'inaccurate', 'support-bad']
			},
			{
				id: 'robinhood',
				name: 'Robinhood',
				volume: 26_670,
				rating: 4.2,
				subcategory: 'Investing',
				loves: ['design', 'features', 'free'],
				hurts: ['crashes', 'support-bad', 'verification']
			}
		]
	},
	{
		id: 'health',
		name: 'Health & Family',
		blurb: 'Fitness, wellbeing and safety',
		apps: [
			{
				id: 'my-fitness-pal',
				name: 'My Fitness Pal',
				volume: 32_305,
				rating: 4.5,
				subcategory: 'Nutrition',
				loves: ['features', 'content', 'design'],
				hurts: ['subscription', 'ads', 'inaccurate']
			},
			{
				id: 'better-me',
				name: 'Better Me',
				volume: 25_282,
				rating: 4.3,
				subcategory: 'Fitness plans',
				loves: ['content', 'personalization', 'design'],
				hurts: ['subscription', 'pricing', 'ads']
			},
			{
				id: 'flo',
				name: 'Flo',
				volume: 43_572,
				rating: 4.7,
				subcategory: 'Cycle tracking',
				loves: ['personalization', 'design', 'content'],
				hurts: ['subscription', 'notifications', 'inaccurate']
			},
			{
				id: 'life360',
				name: 'Life360',
				volume: 52_345,
				rating: 4.6,
				subcategory: 'Family safety',
				loves: ['features', 'security', 'reliability'],
				hurts: ['subscription', 'battery', 'notifications']
			}
		]
	},
	{
		id: 'photo',
		name: 'Photo & Video',
		blurb: 'Editing, enhancement and creation',
		apps: [
			{
				id: 'remini',
				name: 'Remini',
				volume: 154_878,
				rating: 4.5,
				subcategory: 'Photo enhancement',
				loves: ['ai', 'features', 'design'],
				hurts: ['subscription', 'ads', 'pricing']
			},
			{
				id: 'picsart',
				name: 'Picsart',
				volume: 83_357,
				rating: 4.4,
				subcategory: 'Photo editing',
				loves: ['features', 'design', 'content'],
				hurts: ['subscription', 'ads', 'bugs']
			},
			{
				id: 'photoroom',
				name: 'PhotoRoom',
				volume: 39_578,
				rating: 4.5,
				subcategory: 'Product photos',
				loves: ['ai', 'features', 'design'],
				hurts: ['subscription', 'pricing', 'bugs']
			},
			{
				id: 'capcut',
				name: 'CapCut',
				volume: 53_704,
				rating: 4.7,
				subcategory: 'Video editing',
				loves: ['features', 'free', 'ai'],
				hurts: ['ads', 'bugs', 'update']
			}
		]
	},
	{
		id: 'dating',
		name: 'Dating',
		blurb: 'Matches, chats and relationships',
		apps: [
			{
				id: 'tinder',
				name: 'Tinder',
				volume: 77_161,
				rating: 4.0,
				subcategory: 'Dating',
				loves: ['community', 'design', 'features'],
				hurts: ['subscription', 'pricing', 'moderation']
			},
			{
				id: 'hinge',
				name: 'Hinge',
				volume: 38_091,
				rating: 4.2,
				subcategory: 'Dating',
				platform: 'ios',
				loves: ['design', 'features', 'community'],
				hurts: ['subscription', 'pricing', 'bugs']
			},
			{
				id: 'bumble',
				name: 'Bumble',
				volume: 39_397,
				rating: 4.0,
				subcategory: 'Dating',
				platform: 'ios',
				loves: ['community', 'design', 'features'],
				hurts: ['subscription', 'moderation', 'bugs']
			}
		]
	},
	{
		id: 'travel',
		name: 'Travel & Delivery',
		blurb: 'Getting people and things places',
		apps: [
			{
				id: 'uber',
				name: 'Uber',
				volume: 766_987,
				rating: 4.1,
				subcategory: 'Rides',
				loves: ['speed', 'design', 'reliability'],
				hurts: ['pricing', 'fees', 'support-bad']
			},
			{
				id: 'doordash',
				name: 'DoorDash',
				volume: 117_812,
				rating: 4.4,
				subcategory: 'Food delivery',
				loves: ['speed', 'value', 'design'],
				hurts: ['delivery', 'fees', 'support-bad']
			},
			{
				id: 'airbnb',
				name: 'Airbnb',
				volume: 31_434,
				rating: 4.6,
				subcategory: 'Stays',
				loves: ['value', 'design', 'content'],
				hurts: ['fees', 'pricing', 'support-bad']
			},
			{
				id: 'ups',
				name: 'UPS',
				volume: 21_706,
				rating: 4.3,
				subcategory: 'Shipping',
				loves: ['reliability', 'features', 'speed'],
				hurts: ['delivery', 'support-bad', 'inaccurate']
			},
			{
				id: 'spark-driver',
				name: 'Spark Driver',
				volume: 20_538,
				rating: 4.0,
				subcategory: 'Gig delivery',
				platform: 'android',
				loves: ['free', 'features', 'speed'],
				hurts: ['support-bad', 'bugs', 'wait']
			},
			{
				id: 'ticketmaster',
				name: 'Ticketmaster',
				volume: 29_896,
				rating: 4.4,
				subcategory: 'Live events',
				loves: ['features', 'content', 'design'],
				hurts: ['fees', 'pricing', 'wait']
			}
		]
	},
	{
		id: 'games',
		name: 'Games',
		blurb: 'Casual, puzzle and strategy',
		apps: [
			{
				id: 'magic-tiles-3',
				name: 'Magic Tiles 3',
				volume: 84_939,
				rating: 4.5,
				subcategory: 'Music game',
				platform: 'android',
				loves: ['content', 'free', 'design'],
				hurts: ['ads', 'bugs', 'crashes']
			},
			{
				id: 'chess-com',
				name: 'Chess.com',
				volume: 66_742,
				rating: 4.7,
				subcategory: 'Strategy',
				loves: ['features', 'content', 'community'],
				hurts: ['subscription', 'ads', 'bugs']
			},
			{
				id: 'kolibri-games',
				name: 'Kolibri Games',
				volume: 46_557,
				rating: 4.4,
				subcategory: 'Idle games',
				platform: 'android',
				loves: ['content', 'free', 'design'],
				hurts: ['ads', 'pricing', 'bugs']
			}
		]
	},
	{
		id: 'work',
		name: 'Work & Productivity',
		blurb: 'Meetings, hiring and professional networks',
		apps: [
			{
				id: 'linkedin',
				name: 'LinkedIn',
				volume: 76_149,
				rating: 4.2,
				subcategory: 'Professional network',
				loves: ['content', 'features', 'community'],
				hurts: ['ads', 'notifications', 'bugs']
			},
			{
				id: 'indeed',
				name: 'Indeed',
				volume: 180_797,
				rating: 4.5,
				subcategory: 'Job search',
				loves: ['features', 'content', 'design'],
				hurts: ['spam', 'support-bad', 'ads']
			},
			{
				id: 'zoom',
				name: 'Zoom',
				volume: 45_287,
				rating: 4.3,
				subcategory: 'Meetings',
				loves: ['reliability', 'speed', 'features'],
				hurts: ['pricing', 'bugs', 'notifications']
			}
		]
	},
	{
		id: 'utility',
		name: 'Utilities & Browsers',
		blurb: 'Weather, privacy and everyday tools',
		apps: [
			{
				id: 'weather-channel',
				name: 'Weather Channel',
				volume: 48_909,
				rating: 4.5,
				subcategory: 'Weather',
				loves: ['accuracy', 'design', 'features'],
				hurts: ['ads', 'notifications', 'bugs']
			},
			{
				id: 'myradar',
				name: 'MyRadar',
				volume: 44_420,
				rating: 4.6,
				subcategory: 'Weather',
				loves: ['accuracy', 'design', 'features'],
				hurts: ['ads', 'subscription', 'bugs']
			},
			{
				id: 'opera',
				name: 'Opera',
				volume: 68_460,
				rating: 4.4,
				subcategory: 'Browser',
				loves: ['speed', 'free', 'privacy'],
				hurts: ['ads', 'notifications', 'bugs']
			},
			{
				id: 'brave',
				name: 'Brave',
				volume: 88_358,
				rating: 4.5,
				subcategory: 'Browser',
				loves: ['privacy', 'speed', 'free'],
				hurts: ['ads', 'bugs', 'update']
			}
		]
	}
];

interface AppSpec {
	id: string;
	name: string;
	categoryId: string;
	platform: Platform;
	subcategory: string;
	rating: number;
	volume: number;
	loves: string[];
	hurts: string[];
}

const APP_SPECS: AppSpec[] = CATEGORY_SPECS.flatMap((category) =>
	category.apps.map((app) => ({
		id: app.id,
		name: app.name,
		categoryId: category.id,
		platform: app.platform ?? 'both',
		subcategory: app.subcategory,
		rating: app.rating,
		volume: app.volume,
		loves: app.loves,
		hurts: app.hurts
	}))
);

/* ------------------------- generation -------------------------- */

const SAMPLE_PER_APP = 300;
const DAY = 86_400_000;

const OPENERS_POS = [
	'Been using this for a few months now.',
	'Long-time user, first time reviewing.',
	'Switched over last week and I am impressed.',
	'Downloaded it on a whim and stayed.',
	'This has become part of my daily routine.',
	'Tried it on a friend’s phone and had to get it too.'
];
const OPENERS_NEG = [
	'Really wanted to like this.',
	'Used to be my favorite app.',
	'Giving it two stars out of frustration.',
	'This used to work perfectly.',
	'Been patient for months, but no more.',
	'Downloaded it again to give it another chance.'
];
const CLOSERS_POS = [
	'Would recommend to anyone.',
	'Keep it up.',
	'Five stars from me.',
	'This is how it should be done.',
	'Not going back.'
];
const CLOSERS_NEG = [
	'Please fix this.',
	'Looking for alternatives already.',
	'Hoping the next release sorts it out.',
	'Disappointed.',
	'Uninstalling for now.'
];
const DEVICES = ['Pixel 8', 'iPhone 15', 'Galaxy S23', 'OnePlus 12', 'iPad Air', 'older Android phone'];
const DETAILS_POS = [
	'It has replaced everything else on my home screen.',
	'Battery drain is minimal even after hours of use.',
	'Updates land regularly and never break my setup.',
	'I have not hit a single crash in weeks.',
	'Even heavy pages and long sessions stay smooth.',
	'The onboarding took less than a minute.',
	'Everything I need is one tap away.',
	'I recommend it to friends without hesitation.',
	'Support answered my question within a day.',
	'The free tier is generous enough on its own.'
];
const DETAILS_NEG = [
	'It chews through battery even when idle.',
	'Crashes on the same three screens every time.',
	'Updates keep resetting my settings.',
	'It reloads constantly when I switch apps.',
	'My saved data duplicated instead of syncing.',
	'Login flows break on several devices.',
	'Playback stutters in fullscreen.',
	'Downloads disappear if the screen locks.',
	'Search suggestions are consistently irrelevant.',
	'The interface moved everything around in the last update.',
	'Support has not replied in two weeks.',
	'Notifications arrive hours late, if at all.'
];
const DETAILS_NEUTRAL = [
	'Some parts feel polished, others still rough.',
	'It does the basics without much flair.',
	'Results depend heavily on what you are looking for.',
	'I keep it installed as a backup.',
	'Fine for light use, less so for heavy work.',
	'It has improved, but there is still ground to cover.'
];

function makeDistribution(rating: number): number[] {
	// discretised normal, clamped 1..5
	const weights: number[] = [];
	for (let stars = 1; stars <= 5; stars++) {
		const z = (stars - rating) / 1.06;
		weights.push(Math.exp(-0.5 * z * z));
	}
	const total = weights.reduce((a, b) => a + b, 0);
	return weights.map((w) => w / total);
}

function sampleStars(rng: Rand, distribution: number[]): number {
	return chooseWeighted(rng, [1, 2, 3, 4, 5], (s) => distribution[s - 1]) as number;
}

function buildReviewText(
	rng: Rand,
	theme: ThemeSpec | null,
	stars: number,
	sentiment: 'positive' | 'neutral' | 'negative',
	appName: string
): { title: string; text: string } {
	const device = rng() < 0.22 ? choose(rng, DEVICES) : '';
	const opener =
		rng() < 0.42
			? sentiment === 'positive'
				? choose(rng, OPENERS_POS)
				: sentiment === 'negative'
					? choose(rng, OPENERS_NEG)
					: 'Mixed feelings after a couple of weeks.'
			: '';
	const closer =
		rng() < 0.32
			? sentiment === 'positive'
				? choose(rng, CLOSERS_POS)
				: sentiment === 'negative'
					? choose(rng, CLOSERS_NEG)
					: ''
			: '';
	const detail =
		rng() < 0.58
			? choose(
					rng,
					sentiment === 'positive'
						? DETAILS_POS
						: sentiment === 'negative'
							? DETAILS_NEG
							: DETAILS_NEUTRAL
				)
			: '';
	const deviceLine = device && rng() < 0.5 ? `Tested on my ${device}.` : '';

	let core: string;
	if (!theme) {
		core =
			sentiment === 'positive'
				? choose(rng, [
						'Exactly what a mobile app should be.',
						'No complaints so far.',
						'Solid app, does what it says.',
						'Works well for everything I need.'
					])
				: sentiment === 'negative'
					? choose(rng, [
							'Disappointing overall.',
							'Needs a lot more work.',
							'Would not recommend in its current state.'
						])
					: choose(rng, ['It is fine. Does the job.', 'Not bad, not great.']);
	} else if (stars === 3) {
		core = `Mostly solid, but ${theme.phrases[0].charAt(0).toLowerCase()}${theme.phrases[0].slice(1)}`;
	} else {
		core = choose(rng, theme.phrases);
	}

	let text = [opener, core, detail, deviceLine, closer].filter(Boolean).join(' ');

	if (sentiment === 'positive' && theme?.kind === 'negative') {
		text = `Good app overall, though ${core.charAt(0).toLowerCase()}${core.slice(1)}`;
	}

	// Occasionally anchor the review to the product so search hits do not all
	// read like the same template.
	if (rng() < 0.16) {
		text = `${appName} — ${text}`;
	}

	return {
		title: rng() < 0.24 ? `${theme ? theme.label : 'Review'}${device ? ' on mobile' : ''}` : '',
		text: text.replace(/\s+/g, ' ').trim()
	};
}

function buildTrend(rng: Rand, rating: number, volume: number): TrendPoint[] {
	const points: TrendPoint[] = [];
	const weeks = 26;
	const now = Date.now();
	const phase = rng() * Math.PI * 2;
	const drift = (rng() - 0.45) * 0.22;
	for (let i = weeks - 1; i >= 0; i--) {
		const t = (weeks - 1 - i) / (weeks - 1);
		const wobble = Math.sin(t * Math.PI * 3 + phase) * 0.09 + (rng() - 0.5) * 0.07;
		const weekRating = Math.max(1, Math.min(5, rating + wobble + drift * (t - 0.5)));
		const weeklyVolume = Math.round(
			(volume / weeks) * (0.72 + rng() * 0.56) * (0.9 + t * 0.25)
		);
		points.push({
			date: new Date(now - i * 7 * DAY).toISOString(),
			rating: Number(weekRating.toFixed(2)),
			volume: weeklyVolume
		});
	}
	return points;
}

function buildThemes(
	appId: string,
	spec: AppSpec,
	mentions: Map<string, { count: number; examples: string[] }>
): { positive: Theme[]; negative: Theme[] } {
	const positive: Theme[] = [];
	const negative: Theme[] = [];
	const totalReviews = spec.volume;

	for (const themeSpec of [...POSITIVE_THEMES, ...NEGATIVE_THEMES]) {
		const hit = mentions.get(themeSpec.id);
		if (!hit || hit.count < 2) continue;
		const share = hit.count / SAMPLE_PER_APP;
		const theme: Theme = {
			id: themeSpec.id,
			label: themeSpec.label,
			kind: themeSpec.kind,
			count: Math.round(share * totalReviews),
			share,
			examples: hit.examples.slice(0, 3),
			appIds: [appId]
		};
		if (themeSpec.kind === 'positive') positive.push(theme);
		else negative.push(theme);
	}

	positive.sort((a, b) => b.share - a.share);
	negative.sort((a, b) => b.share - a.share);
	return { positive, negative };
}

function buildCategoryAggregates(categories: Category[], apps: AppNode[]): void {
	for (const category of categories) {
		const owned = apps.filter((a) => a.categoryId === category.id);
		category.appIds = owned.map((a) => a.id);
		const volume = owned.reduce((sum, a) => sum + a.reviewCount, 0) || 1;
		category.reviewCount = volume;
		category.rating = Number(
			(owned.reduce((sum, a) => sum + a.rating * a.reviewCount, 0) / volume).toFixed(2)
		);
		category.reception = Math.round(
			owned.reduce((sum, a) => sum + a.reception * a.reviewCount, 0) / volume
		);
		category.receptionDelta = Number(
			(
				owned.reduce((sum, a) => sum + a.receptionDelta * a.reviewCount, 0) / volume
			).toFixed(1)
		);
	}
}

function cosine(a: Map<string, number>, b: Map<string, number>): number {
	let dot = 0;
	let na = 0;
	let nb = 0;
	for (const v of a.values()) na += v * v;
	for (const [k, v] of b) {
		nb += v * v;
		const av = a.get(k);
		if (av) dot += av * v;
	}
	if (na === 0 || nb === 0) return 0;
	return dot / (Math.sqrt(na) * Math.sqrt(nb));
}

function themeVector(spec: AppSpec): Map<string, number> {
	const vector = new Map<string, number>();
	for (const id of spec.loves) vector.set(id, (vector.get(id) ?? 0) + 1);
	for (const id of spec.hurts) vector.set(id, (vector.get(id) ?? 0) + 0.8);
	vector.set(`platform:${spec.platform}`, 0.4);
	return vector;
}

function buildSimilarities(apps: AppNode[], specs: AppSpec[]) {
	const byId = new Map(specs.map((s) => [s.id, s]));
	const vectors = new Map(specs.map((s) => [s.id, themeVector(s)]));
	const pairs: { source: string; target: string; score: number }[] = [];
	const seen = new Set<string>();

	for (const a of apps) {
		const specA = byId.get(a.id);
		const va = vectors.get(a.id);
		if (!specA || !va) continue;

		const scored = apps
			.filter((b) => b.id !== a.id)
			.map((b) => {
				const specB = byId.get(b.id);
				const similarity = cosine(va, vectors.get(b.id) ?? new Map());
				const bonus = specB?.categoryId === specA.categoryId ? 0.22 : 0;
				return { appId: b.id, score: Math.min(1, similarity + bonus) };
			})
			.filter((s) => s.score > 0.32)
			.sort((x, y) => y.score - x.score);

		const sameCategory = scored.filter((s) => byId.get(s.appId)?.categoryId === specA.categoryId);
		const crossCategory = scored.filter((s) => byId.get(s.appId)?.categoryId !== specA.categoryId);
		const picked = [...sameCategory.slice(0, 2), ...crossCategory.slice(0, 1)]
			.sort((x, y) => y.score - x.score)
			.slice(0, 3);

		a.similar = picked.map((s) => ({ appId: s.appId, score: Number(s.score.toFixed(3)) }));

		for (const s of picked) {
			const key = [a.id, s.appId].sort().join('::');
			if (seen.has(key)) continue;
			seen.add(key);
			pairs.push({ source: a.id, target: s.appId, score: Number(s.score.toFixed(3)) });
		}
	}
	return pairs;
}

function makeThemesRollup(apps: AppNode[]): Theme[] {
	const map = new Map<string, Theme>();
	const totalReviews = apps.reduce((sum, a) => sum + a.reviewCount, 0) || 1;

	for (const app of apps) {
		for (const theme of [...app.themes.positive, ...app.themes.negative]) {
			const existing = map.get(theme.id);
			if (existing) {
				existing.count += theme.count;
				existing.appIds.push(app.id);
				existing.examples.push(...theme.examples);
				existing.impact = mergeImpact(existing.impact, theme.impact);
			} else {
				map.set(theme.id, {
					...theme,
					examples: [...theme.examples],
					appIds: [app.id]
				});
			}
		}
	}

	const out = [...map.values()];
	for (const theme of out) {
		theme.share = Math.min(1, theme.count / totalReviews);
		theme.examples = [...new Set(theme.examples)].slice(0, 4);
		theme.appIds = [...new Set(theme.appIds)];
	}
	return out.sort((a, b) => b.count - a.count);
}

/* ---------------------- review → download signals ---------------- */

interface DownloadWeek {
	date: string;
	downloads: number;
}

/** Weekly sampling weights: more reviews in high-download weeks, and theme
 *  mentions skewed toward the week before a rise (positive themes) or a dip
 *  (negative themes). This is what gives the demo coherent correlations. */
function buildWeekWeights(downloads: number[], affinity: number): number[] {
	if (!downloads.length) return [];
	const max = Math.max(...downloads, 1);
	const momentum = downloads.map((value, index) => {
		const next = downloads[index + 1];
		if (next == null) return 0;
		return (next - value) / Math.max(1, value);
	});
	return downloads.map((value, index) => {
		const base = 0.4 + 0.6 * (value / max);
		const lead = Math.max(-0.4, Math.min(0.4, momentum[index] ?? 0));
		return Math.max(0.02, base * (1 + affinity * 0.9 * lead));
	});
}

function pickWeek(rng: Rand, weights: number[]): number {
	const total = weights.reduce((sum, weight) => sum + weight, 0);
	if (total <= 0) return Math.floor(rng() * weights.length);
	let r = rng() * total;
	for (let i = 0; i < weights.length; i++) {
		r -= weights[i];
		if (r <= 0) return i;
	}
	return weights.length - 1;
}

function weekIndexFor(date: string, weeks: DownloadWeek[]): number {
	if (!weeks.length) return 0;
	const first = new Date(weeks[0].date).getTime();
	const index = Math.round((new Date(date).getTime() - first) / (7 * DAY));
	return Math.max(0, Math.min(weeks.length - 1, index));
}

function emptySignal(
	id: string,
	label: string,
	kind: CorrelationSignal['kind'],
	weeks: number
): CorrelationSignal {
	return { id, label, kind, r: 0, lag: 0, n: weeks, mentions: 0, confidence: 'low' };
}

/** Attach weekly review series and download correlations to an app + themes. */
function buildSignals(app: AppNode, reviews: Review[], weeks: DownloadWeek[]): void {
	if (!weeks.length || !reviews.length) return;
	const n = weeks.length;
	const counts = new Array<number>(n).fill(0);
	const positive = new Array<number>(n).fill(0);
	const negative = new Array<number>(n).fill(0);
	const ratingSum = new Array<number>(n).fill(0);
	const themeCounts = new Map<string, number[]>();

	for (const review of reviews) {
		const index = weekIndexFor(review.date, weeks);
		counts[index]++;
		if (review.sentiment === 'positive') positive[index]++;
		if (review.sentiment === 'negative') negative[index]++;
		ratingSum[index] += review.stars;
		for (const themeId of review.themeIds ?? []) {
			const series = themeCounts.get(themeId) ?? new Array<number>(n).fill(0);
			series[index]++;
			themeCounts.set(themeId, series);
		}
	}

	const weekly: SignalWeek[] = weeks.map((week, index) => ({
		date: week.date,
		reviews: counts[index],
		positive: positive[index],
		negative: negative[index],
		rating: counts[index] ? Number((ratingSum[index] / counts[index]).toFixed(2)) : 0
	}));

	const downloads = weeks.map((week) => week.downloads);
	const negativeShare = counts.map((count, index) => (count ? negative[index] / count : 0));
	const totalNegative = negative.reduce((sum, value) => sum + value, 0);

	const volume =
		signal('volume', 'Review volume', 'neutral', counts, downloads, reviews.length, 1) ??
		emptySignal('volume', 'Review volume', 'neutral', n);
	const sentiment =
		signal('sentiment', 'Negative reviews', 'negative', negativeShare, downloads, totalNegative, 2) ??
		emptySignal('sentiment', 'Negative reviews', 'negative', n);

	const drivers: CorrelationSignal[] = [];
	for (const theme of [...app.themes.positive, ...app.themes.negative]) {
		const series = themeCounts.get(theme.id);
		if (!series) continue;
		const mentions = series.reduce((sum, value) => sum + value, 0);
		if (mentions < 6) continue;
		const share = series.map((value, index) => (counts[index] ? value / counts[index] : 0));
		const result = signal(theme.id, theme.label, theme.kind, share, downloads, mentions, 2);
		if (!result) continue;
		theme.impact = {
			r: result.r,
			lag: result.lag,
			n: result.n,
			mentions,
			confidence: result.confidence
		};
		const expected = theme.kind === 'positive' ? result.r : -result.r;
		if (expected >= 0.15) drivers.push(result);
	}
	drivers.sort((a, b) => {
		const ea = a.kind === 'positive' ? a.r : -a.r;
		const eb = b.kind === 'positive' ? b.r : -b.r;
		return eb - ea;
	});

	app.signals = { weekly, volume, sentiment, drivers: drivers.slice(0, 5) };
}

/* ------------------------- dataset build ----------------------- */

interface DemoDataset {
	graph: GraphPayload;
	reviews: Review[];
	byApp: Map<string, Review[]>;
}

let cached: DemoDataset | null = null;

function buildDataset(): DemoDataset {
	const rng = mulberry32(0x9e3779b9);
	const now = Date.now();

	const categories: Category[] = CATEGORY_SPECS.map((category, index) => ({
		id: category.id,
		name: category.name,
		blurb: category.blurb,
		appIds: [],
		rating: 0,
		reviewCount: 0,
		reception: 0,
		receptionDelta: 0,
		accent: accentFor(index)
	}));

	const apps: AppNode[] = [];
	const reviews: Review[] = [];
	const byApp = new Map<string, Review[]>();

	for (const spec of APP_SPECS) {
		const category = categories.find((c) => c.id === spec.categoryId)!;
		const distribution = makeDistribution(spec.rating);
		const mentions = new Map<string, { count: number; examples: string[] }>();
		const appReviews: Review[] = [];
		const sentiment = { positive: 0, neutral: 0, negative: 0 };
		const starCounts: Record<number, number> = { 1: 0, 2: 0, 3: 0, 4: 0, 5: 0 };
		const sources: Record<string, number> = { gplay: 0, appstore: 0 };
		const downloadWeeks = downloadStats(spec.id)?.weekly ?? [];
		const downloadSeries = downloadWeeks.map((week) => week.downloads);
		const neutralWeights = buildWeekWeights(downloadSeries, 0);
		const themeWeights = new Map<string, number[]>();
		for (const themeSpec of [...POSITIVE_THEMES, ...NEGATIVE_THEMES]) {
			themeWeights.set(
				themeSpec.id,
				buildWeekWeights(downloadSeries, themeSpec.kind === 'positive' ? 1 : -1)
			);
		}

		for (let i = 0; i < SAMPLE_PER_APP; i++) {
			const stars = sampleStars(rng, distribution);
			const sentimentKind = sentimentFromStars(stars);
			let themeSpec: ThemeSpec | null;

			if (stars >= 4) {
				themeSpec = rng() < 0.9 ? THEME_BY_ID.get(choose(rng, spec.loves))! : null;
			} else if (stars <= 2) {
				themeSpec = rng() < 0.9 ? THEME_BY_ID.get(choose(rng, spec.hurts))! : null;
			} else {
				const useNegative = rng() < 0.6;
				themeSpec = THEME_BY_ID.get(choose(rng, useNegative ? spec.hurts : spec.loves))!;
			}

			const source =
				spec.platform === 'android'
					? 'gplay'
					: spec.platform === 'ios'
						? 'appstore'
						: rng() < 0.68
							? 'gplay'
							: 'appstore';

			const { title, text } = buildReviewText(rng, themeSpec, stars, sentimentKind, spec.name);
			// Sample review dates from the download curve so review volume and
			// theme mix co-move with installs. Fall back to recency when a demo
			// download series is unavailable.
			let date: string;
			if (downloadWeeks.length) {
				const weights =
					(themeSpec ? themeWeights.get(themeSpec.id) : null) ?? neutralWeights;
				const week = pickWeek(rng, weights.length ? weights : neutralWeights);
				const base = new Date(downloadWeeks[week].date).getTime();
				const jitter = Math.floor(rng() * 6) * DAY;
				date = new Date(Math.min(now, base + jitter)).toISOString();
			} else {
				const daysAgo = Math.floor(Math.pow(rng(), 1.7) * 180);
				date = new Date(now - daysAgo * DAY).toISOString();
			}

			const review: Review = {
				id: `rv-${spec.id}-${i}`,
				appId: spec.id,
				appName: spec.name,
				categoryId: spec.categoryId,
				stars,
				date,
				title,
				text,
				source,
				version: `v1.${40 + Math.floor(rng() * 30)}.${Math.floor(rng() * 9)}`,
				sentiment: sentimentKind,
				themeIds: themeSpec ? [themeSpec.id] : []
			};

			appReviews.push(review);
			reviews.push(review);

			sentiment[sentimentKind]++;
			starCounts[stars]++;
			sources[source]++;

			if (themeSpec) {
				const hit = mentions.get(themeSpec.id) ?? { count: 0, examples: [] };
				hit.count++;
				if (hit.examples.length < 4) hit.examples.push(text);
				mentions.set(themeSpec.id, hit);
			}
		}

		const trend = buildTrend(rng, spec.rating, spec.volume);
		const recent = trend.slice(-4);
		const previous = trend.slice(-8, -4);
		const avg = (arr: TrendPoint[]) => arr.reduce((s, p) => s + p.rating, 0) / arr.length;
		const reception = Math.round(
			0.58 * (((spec.rating - 1) / 4) * 100) +
				0.42 * ((sentiment.positive / SAMPLE_PER_APP) * 100)
		);
		const delta = Number(((avg(recent) - avg(previous)) * 14).toFixed(1));

		const app: AppNode = {
			id: spec.id,
			name: spec.name,
			categoryId: spec.categoryId,
			categoryName: category.name,
			platform: spec.platform,
			subcategory: spec.subcategory,
			rating: Number(spec.rating.toFixed(2)),
			reviewCount: spec.volume,
			reception,
			receptionDelta: delta,
			sentiment: {
				positive: Math.round((sentiment.positive / SAMPLE_PER_APP) * spec.volume),
				neutral: Math.round((sentiment.neutral / SAMPLE_PER_APP) * spec.volume),
				negative: Math.round((sentiment.negative / SAMPLE_PER_APP) * spec.volume)
			},
			distribution: ([1, 2, 3, 4, 5] as const).map((stars) => ({
				stars,
				count: Math.round((starCounts[stars] / SAMPLE_PER_APP) * spec.volume)
			})),
			trend,
			themes: buildThemes(spec.id, spec, mentions),
			similar: [],
			sources,
			accent: category.accent
		};

		apps.push(app);
		buildSignals(app, appReviews, downloadWeeks);
		byApp.set(app.id, appReviews);
	}

	const edges = buildSimilarities(apps, APP_SPECS);
	buildCategoryAggregates(categories, apps);

	const totalReviews = apps.reduce((sum, a) => sum + a.reviewCount, 0);
	const avgRating = apps.reduce((sum, a) => sum + a.rating * a.reviewCount, 0) / totalReviews;
	const sourceCounts = { gplay: 0, appstore: 0 };
	for (const app of apps) {
		sourceCounts.gplay += app.sources.gplay ?? 0;
		sourceCounts.appstore += app.sources.appstore ?? 0;
	}
	const totalSourceSamples = sourceCounts.gplay + sourceCounts.appstore || 1;

	const graph: GraphPayload = {
		meta: {
			label: 'App Store Feedback · Multi-category Corpus',
			generatedAt: new Date(now).toISOString(),
			reviewCount: totalReviews,
			sampled: reviews.length,
			appCount: apps.length,
			categoryCount: categories.length,
			embeddingDim: 768,
			embeddingModel: 'text-embedding-3-small',
			avgRating: Number(avgRating.toFixed(2)),
			window: {
				from: new Date(now - 180 * DAY).toISOString(),
				to: new Date(now).toISOString()
			},
			sources: [
				{
					id: 'gplay',
					name: 'Google Play',
					count: Math.round((sourceCounts.gplay / totalSourceSamples) * totalReviews)
				},
				{
					id: 'appstore',
					name: 'App Store',
					count: Math.round((sourceCounts.appstore / totalSourceSamples) * totalReviews)
				}
			]
		},
		categories,
		apps,
		edges,
		themes: makeThemesRollup(apps)
	};

	return { graph, reviews, byApp };
}

function dataset(): DemoDataset {
	if (!cached) cached = buildDataset();
	return cached;
}

/* --------------------------- search ---------------------------- */

const STOPWORDS = new Set([
	'the','a','an','and','or','but','is','are','was','were','be','been','to','of','in','on','for',
	'with','it','this','that','these','those','my','i','me','we','you','your','app','apps','really',
	'very','so','just','not','no','have','has','had','can','cant','cannot','dont','doesnt','do',
	'does','did','as','at','by','from','about','like','get','got','would','could','should','when',
	'there','their','they','them','he','she','his','her','its','if','than','then','too','also','up'
]);

function tokens(text: string): string[] {
	return text
		.toLowerCase()
		.replace(/[^a-z0-9\s]/g, ' ')
		.split(/\s+/)
		.filter((t) => t.length > 1 && !STOPWORDS.has(t));
}

/* ----------------------------- API ----------------------------- */

export class MockApi implements UnwrapApi {
	async getGraph(): Promise<GraphPayload> {
		await delay(260);
		return structuredClone(dataset().graph);
	}

	async getReviews(appId: string, query: { limit?: number; stars?: number; sentiment?: string } = {}) {
		await delay(90);
		const all = dataset().byApp.get(appId) ?? [];
		let filtered = all;
		if (query.stars) filtered = filtered.filter((r) => r.stars === query.stars);
		if (query.sentiment) filtered = filtered.filter((r) => r.sentiment === query.sentiment);
		return structuredClone(filtered.slice(0, query.limit ?? 80));
	}

	async searchReviews(query: string, options: SearchOptions = {}): Promise<SearchHit[]> {
		await delay(180);
		const qTokens = [...new Set(tokens(query))];
		if (qTokens.length === 0) return [];

		const pool = options.appId
			? (dataset().byApp.get(options.appId) ?? [])
			: dataset().reviews;

		const phrase = query.toLowerCase().trim();
		const scored = pool
			.filter((r) => !options.minStars || r.stars >= options.minStars)
			.map((review) => {
				const haystack = `${review.title} ${review.text}`.toLowerCase();
				const reviewTokens = new Set(tokens(haystack));
				let hits = 0;
				for (const t of qTokens) {
					if (reviewTokens.has(t)) hits += 1;
					else if (haystack.includes(t)) hits += 0.7;
				}
				let score = hits / qTokens.length;
				if (phrase.length > 3 && haystack.includes(phrase)) score += 0.2;
				if (review.themeIds?.some((id) => qTokens.includes(id))) score += 0.05;
				// small recency nudge
				const age = (Date.now() - new Date(review.date).getTime()) / DAY;
				score += Math.max(0, 0.04 - age / 5000);
				return { review, score: Math.min(1, score) };
			})
			.filter((r) => r.score > 0.28)
			.sort((a, b) => b.score - a.score)
			.slice(0, options.limit ?? 24);

		return scored.map(({ review, score }) => ({
			...structuredClone(review),
			score: Number(score.toFixed(2))
		}));
	}

	async health() {
		return { ok: true, detail: 'demo dataset' };
	}
}

function delay(ms: number) {
	return new Promise((resolve) => setTimeout(resolve, ms));
}
