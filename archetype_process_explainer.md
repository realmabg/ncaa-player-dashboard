# Archetype Beta Process Explainer

This document explains the new archetype beta work in plain language for coaches, managers, and other basketball staff. It is meant to describe what the dashboard is doing, what the PCA map means, and what the results should and should not be used for.

## Purpose

The goal is to turn the staff's preferred player profiles into a searchable, visual tool.

The current focus is on three archetypes:

1. **PG / Combo Guard**
2. **2-4 Interchangeable Wing**
3. **5 / Stretch 4 / Big Wing**

Each player is evaluated against the traits staff described: passing/creation, shooting quality, shooting volume, ball security, defensive rebounding, and size.

This is a **beta** model. It is designed to help surface players for review, not to make final decisions by itself.

## Data Used

The archetype beta uses three datasets:

- **Division I:** `mbb_with_pca.csv`
- **Division II:** `d2_data_cleaned.csv`
- **Division III:** `d3_data_cleaned.csv`

The model does not modify these files. All new scores and PCA coordinates are created in memory when the notebook or website runs.

## The Three Archetypes

### PG / Combo Guard

This profile is looking for high-level guard creation.

Important traits:

- High assist creation
- Strong 3P percentage
- Enough 3P volume to be a real spacing threat
- Positive assist-to-turnover ratio
- Ability to create paint touches or advantages

The staff thresholds used in the beta are:

- 3P% around **33%+**
- 3P rate around **30%+**
- Positive A/TO ratio
- Strong assist creation compared with other players in the same division

### 2-4 Interchangeable Wing

This profile is looking for bigger perimeter or forward-type players who can space, rebound, and keep the ball moving.

Important traits:

- Defensive rebounding
- 3P shooting quality
- 3P shooting volume
- Positive A/TO ratio
- Positional versatility

The staff thresholds used in the beta are:

- 3P% around **33%+**
- 3P rate around **30%+**
- Positive A/TO ratio
- Strong defensive rebounding profile

### 5 / Stretch 4 / Big Wing

This profile is looking for bigger players who can rebound and still provide shooting value.

Important traits:

- Size, generally **6'7"+**
- Defensive rebounding
- 3P shooting quality
- Enough 3P volume to matter
- Positive A/TO ratio

The staff thresholds used in the beta are:

- Height around **6'7"+**
- 3P% around **30%+**
- 3P rate around **25%+**
- Positive A/TO ratio
- Strong defensive rebounding profile

## How Players Are Scored

Each player receives three archetype scores:

- `PG / Combo Guard` score
- `2-4 Interchangeable Wing` score
- `5 / Stretch 4 / Big Wing` score

The highest score becomes the player's **primary archetype**.

For example, if a player scores:

- PG / Combo Guard: 82
- 2-4 Wing: 67
- Stretch Big: 41

Then the player's primary archetype is **PG / Combo Guard**.

## Soft Rules, Not Hard Cuts

The model does not automatically remove players who miss one threshold.

That is intentional.

Staff noted that a player may still be interesting if they are exceptional in one area, even if they miss another area. For example:

- A guard may be worth reviewing if they have elite assist creation, even if their 3P% is slightly below target.
- A wing may be worth reviewing if they rebound extremely well and have positive A/TO, even if their shooting is borderline.
- A big may be worth reviewing if they are a strong rebounder and credible shooter, even if their 3P volume is not ideal.

Because of that, the scores are built as **fit scores**, not yes/no labels.

## How Stats Are Compared Across Divisions

Division I, Division II, and Division III do not always have the exact same stats available.

To make players easier to compare, most archetype inputs are converted into **percentile scores within the player's division**.

In plain language:

> A player's assist creation score is based on how they compare to other players in their division, not just the raw number.

This helps avoid treating raw D-I, D-II, and D-III numbers as if they came from identical stat environments.

## Exact Stats And Proxies

Some stats are available directly. Others require proxies.

### Assist Creation

- **D-I:** uses `AST_pct`, a true assist-rate style stat.
- **D-II / D-III:** uses `ast_per_40` as a proxy.

This means D-I assist creation is more exact. D-II and D-III assist creation should be read as an estimate based on available data.

### Defensive Rebounding

- **D-I:** uses `DRB_pct`, a true defensive rebounding rate.
- **D-II / D-III:** uses `DRBPG` as a proxy.

For D-II and D-III, defensive rebounding is also adjusted by position group so guards are not judged the same way as bigs.

### Shooting Quality

Uses 3P percentage:

- D-I: `3P_pct`
- D-II / D-III: `3PT%`

### Shooting Volume

Uses 3P share / 3P rate:

- D-I / D-II / D-III: `three_share`

### Ball Security

Uses assist-to-turnover ratio:

- D-I / D-II / D-III: `AST_TOV`

### Size

Uses height in inches.

## What PCA Is Doing

PCA is a way to turn several related traits into a simple map.

Instead of looking at seven different numbers at once, PCA creates map coordinates that summarize major patterns in the data.

For this project, PCA uses these archetype traits:

- Assist creation
- 3P shooting quality
- 3P shooting volume
- A/TO
- Overall shooting efficiency
- Position-adjusted defensive rebounding
- Size / height

The result is a scatterplot where each player has:

- an x-axis value
- a y-axis value
- a color based on primary archetype

## How To Read The Archetype PCA Map

The new beta dashboards use:

- **X-axis:** PC1
- **Y-axis:** PC2
- **Color:** primary archetype

### PC1: Size vs Creator Guard Traits

PC1 mostly separates bigger players from creator-guard profiles.

Higher PC1 generally means:

- more size
- less guard-creation profile

Lower PC1 generally means:

- stronger A/TO
- stronger assist creation
- more 3P volume
- more guard-like creation traits

Plain-language label:

> **Size vs Creator Guard Traits**

### PC2: Shooting / Spacing Strength

PC2 mostly separates strong shooting profiles from less shooting-driven profiles.

Higher PC2 generally means:

- better 3P percentage
- better overall shooting efficiency
- more 3P volume

Lower PC2 generally means:

- less shooting-driven profile
- more value may come from creation, rebounding, or other traits

Plain-language label:

> **Shooting / Spacing Strength**

## Why Points Are Colored By Archetype

Each dot is colored by the player's strongest archetype score.

Suggested colors:

- **PG / Combo Guard:** blue
- **2-4 Interchangeable Wing:** green
- **5 / Stretch 4 / Big Wing:** orange

This lets staff quickly see where different archetype groups appear on the PCA map.

For example:

- A blue cluster on the lower-PC1 side likely represents creator guards.
- Orange players higher on PC1 may represent bigger stretch or frontcourt profiles.
- Green players may sit between guards and bigs, depending on shooting, rebounding, and A/TO.

## What The Dashboard Is Good For

The archetype beta is useful for:

- finding players who match staff-defined profiles
- comparing players within a division
- spotting outliers
- identifying strong PG / combo guard candidates
- seeing whether a player is a shooter, creator, rebounder, or hybrid
- giving staff a better first-pass screening tool

## What The Dashboard Should Not Do

The archetype beta should not be treated as a final player ranking.

It does not know:

- role context
- scheme fit
- defensive assignment difficulty
- shot quality
- off-ball gravity
- injury context
- personality / coachability
- transfer likelihood
- academic or eligibility details
- film-based decision-making

It should help staff decide who to watch more closely, not replace scouting.

## Recommended Workflow For Staff

1. Start with the relevant division's **Archetype Beta** dashboard.
2. Filter to the archetype of interest.
3. For current priorities, start with **PG / Combo Guard**.
4. Use score filters to narrow the pool.
5. Check shooting filters:
   - 3P%
   - 3P rate
6. Check ball security:
   - A/TO
7. Review players on the PCA map:
   - PC1 for size vs creator profile
   - PC2 for shooting / spacing
8. Use the hover tooltip to review each player's profile.
9. Move interesting names into a watchlist or film review process.

## Important Caveats

### D-II And D-III Use Proxies

D-II and D-III do not have every exact rate stat available, so some values are estimates based on the cleaned data.

This matters most for:

- assist creation
- defensive rebounding

### PCA Axes Are Not Fixed Basketball Truths

PCA axes are based on patterns in the current dataset. If the dataset or features change, the axes may change.

That is why the dashboard is labeled **Beta**.

### Scores Are Relative

Most feature scores are percentile-based within division. A strong D-II percentile means strong relative to D-II players in the dataset. It does not automatically mean the same thing as the same percentile in D-I.

## Summary

The archetype beta translates staff-defined player profiles into a data tool.

It:

- scores players against three target archetypes
- keeps players visible even if they miss one threshold
- uses percentiles to compare players more fairly within division
- creates a PCA map to visualize player style
- colors players by strongest archetype fit

The best use of the tool is as a first-pass scouting and screening layer. It should help staff find players worth watching, discussing, and validating on film.
