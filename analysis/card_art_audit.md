# card art audit — is each cached card portrait really a portrait?

The maintainer spotted it first: "some card art is coming out inconsistent... so
far I've identified Wildfire Elemental and Sellemental." Both were in Settle Up's
Turn 15, drawn as framed cards with their name and rules text, while the cards
beside them were full-bleed art.

## What was wrong

`/img/<id>.png` serves `img_cache/<id>.png` as the square art a tile draws. A card
RENDER — the framed layout WITH the name and the rules text — is a different
picture of the same card, and art is cached per id forever (content-addressed by
id, served `max-age=604800`). So one wrong write under that name shows the wrong
picture on every page that draws the card, indefinitely, and nothing notices: the
file exists, the server returns 200, and the tile renders a framed card where its
neighbours show art.

It was never the two cards the maintainer found. **106 of 943 cached portraits were
card renders** — 11% — including HEROES (`BG20_HERO_283` = Galewing: cached as a
framed hero card, upstream `orig` is the gryphon art) and cards from every set
back to `BG19`.

## Method

Fetch the canonical portrait — the SAME source `/img/` would use,
`coach_ui.PORTRAIT_URLS` = `https://art.hearthstonejson.com/v1/orig/{}.png` — and
compare a 32x32 grayscale signature. A true portrait of the same art scores ~0
against it; a card render scores tens.

Calibrated before use, on four files where the answer was already known:

| card | signature diff |
| --- | --- |
| `BGS_126` Wildfire Elemental (broken) | **61.6** |
| `BGS_115` Sellemental (broken) | **60.6** |
| `BG35_881` Leyline Surfacer (fine) | 0.1 |
| `BG36_640` Gatekeeper Amalgam (fine) | 0.1 |

`analysis/audit_card_art.py --threshold 15` sits between them, and the tool was
then confirmed by eye on one flagged card AND one flagged hero before it was
allowed to change anything.

## The finding

943 portraits checked · 837 consistent · **106 inconsistent** · 0 with no portrait
upstream (so nothing had to be left alone).

The inconsistent ids, in full:

- `BG19_010`  signature diff 106.7
- `BG20_HERO_283`  signature diff 90.0
- `BG21_HERO_010`  signature diff 69.1
- `BG21_HERO_020`  signature diff 67.1
- `BG22_202`  signature diff 55.6
- `BG22_HERO_201p`  signature diff 27.0
- `BG23_002`  signature diff 58.1
- `BG23_008`  signature diff 92.6
- `BG23_318`  signature diff 62.5
- `BG24_004`  signature diff 100.8
- `BG24_018`  signature diff 115.9
- `BG25_003`  signature diff 107.1
- `BG25_005`  signature diff 105.3
- `BG25_009`  signature diff 104.5
- `BG25_011`  signature diff 95.2
- `BG25_034`  signature diff 111.8
- `BG25_806`  signature diff 104.0
- `BG26_137`  signature diff 105.2
- `BG26_146`  signature diff 64.6
- `BG26_147`  signature diff 92.7
- `BG26_148`  signature diff 115.8
- `BG26_175`  signature diff 99.5
- `BG26_354`  signature diff 109.0
- `BG26_361`  signature diff 79.8
- `BG26_505`  signature diff 100.7
- `BG26_523`  signature diff 96.0
- `BG26_525`  signature diff 90.8
- `BG26_814`  signature diff 107.1
- `BG26_817`  signature diff 114.6
- `BG26_CFM_636`  signature diff 107.1
- `BG26_HERO_102`  signature diff 65.8
- `BG26_HERO_104`  signature diff 43.1
- `BG26_ICC_026`  signature diff 101.6
- `BG26_ICC_901`  signature diff 112.1
- `BG26_OG_248`  signature diff 76.1
- `BG27_002`  signature diff 98.1
- `BG27_005`  signature diff 104.3
- `BG27_016`  signature diff 93.3
- `BG27_017`  signature diff 87.1
- `BG27_080`  signature diff 95.3
- `BG27_513`  signature diff 103.2
- `BG27_514`  signature diff 101.9
- `BG28_168`  signature diff 38.4
- `BG28_303`  signature diff 102.4
- `BG28_500`  signature diff 89.4
- `BG28_521`  signature diff 67.4
- `BG28_595`  signature diff 99.8
- `BG28_601`  signature diff 96.1
- `BG28_603`  signature diff 76.6
- `BG28_604`  signature diff 76.8
- `BG28_606`  signature diff 66.6
- `BG28_607`  signature diff 58.8
- `BG28_633`  signature diff 65.1
- `BG28_698`  signature diff 48.4
- `BG28_741`  signature diff 94.8
- `BG28_805`  signature diff 91.4
- `BG28_827`  signature diff 94.1
- `BG28_845`  signature diff 50.4
- `BG28_882`  signature diff 93.4
- `BG28_884`  signature diff 75.5
- `BG28_886`  signature diff 73.7
- `BG28_GIL_836`  signature diff 106.2
- `BG30_MagicItem_425`  signature diff 60.9
- `BG30_MagicItem_544`  signature diff 55.0
- `BG31_886`  signature diff 23.5
- `BG32_MagicItem_888`  signature diff 16.2
- `BG34_990`  signature diff 39.3
- `BG35_149`  signature diff 37.3
- `BG35_MagicItem_150`  signature diff 50.2
- `BG35_MagicItem_816`  signature diff 30.0
- `BG35_MagicItem_861`  signature diff 45.7
- `BGS_004`  signature diff 103.7
- `BGS_012`  signature diff 108.9
- `BGS_018`  signature diff 67.1
- `BGS_020`  signature diff 32.6
- `BGS_041`  signature diff 64.1
- `BGS_071`  signature diff 98.0
- `BGS_104`  signature diff 101.7
- `BGS_115`  signature diff 60.6
- `BGS_116`  signature diff 32.0
- `BGS_119`  signature diff 81.1
- `BGS_123`  signature diff 97.7
- `BGS_126`  signature diff 61.6
- `BGS_127`  signature diff 92.5
- `BGS_131`  signature diff 93.5
- `BG_BOT_911`  signature diff 99.5
- `BG_DEEP_015`  signature diff 90.2
- `BG_ICC_094`  signature diff 62.3
- `BG_RLK_957`  signature diff 101.6
- `BG_TTN_401`  signature diff 43.7
- `BG_ULD_275`  signature diff 97.4
- `EBG_Spell_032`  signature diff 81.4
- `EBG_Spell_037`  signature diff 34.7
- `EBG_Spell_038`  signature diff 72.2
- `TB_BaconShop_HERO_08`  signature diff 64.2
- `TB_BaconShop_HERO_11`  signature diff 72.5
- `TB_BaconShop_HERO_15`  signature diff 68.0
- `TB_BaconShop_HERO_23`  signature diff 58.8
- `TB_BaconShop_HERO_27`  signature diff 78.7
- `TB_BaconShop_HERO_28`  signature diff 78.6
- `TB_BaconShop_HERO_36`  signature diff 53.5
- `TB_BaconShop_HERO_41`  signature diff 83.3
- `TB_BaconShop_HERO_58`  signature diff 71.3
- `TB_BaconShop_HERO_67`  signature diff 66.0
- `TB_BaconShop_HERO_72`  signature diff 87.5
- `TB_BaconShop_HERO_74`  signature diff 88.4

## The repair

`analysis/audit_card_art.py --fix` re-fetched each inconsistent id from the
portrait source and replaced the file with that art, downscaled to 256x256
(atomic write: `.tmp` then rename). Nothing was deleted, and no id that the
portrait source lacks was touched.

**Verified by re-running the same audit afterwards: 943 checked, 943 consistent,
0 inconsistent.**

## Why it happened, and what would catch it next time

The current `/img/` handler fetches ONLY the portrait chain (`_fetch_render(cid)`
with `card=False`), and the `/card/` handler is the one that writes renders, into
`img_cache/card/`. So the poisoning is HISTORICAL — an older write path put a
render under the portrait name, and the per-id cache then made it permanent.

The audit is the guard: it is cheap (one request per cached id), re-runnable, and
it is the only thing that can see this, because the failure is invisible from the
server's side. Worth running after a big ingest or before a release.

## One caveat for the maintainer

The overlay serves art with `Cache-Control: public, max-age=604800`, so a browser
that already drew the broken art will keep showing it for up to 7 days. **Hard
refresh the overlay page (Cmd-Shift-R) once** to see the repaired set.
