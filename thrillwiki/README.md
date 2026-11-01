# ThrillWiki

Look up theme parks, rides and companies from [ThrillWiki](https://www.thrillwiki.com/) without leaving Discord. It talks to the public API, so there's nothing to configure and no key to get.

## Install

```
[p]repo add Pac-cogs https://github.com/pacnpal/Pac-cogs
[p]cog install Pac-cogs thrillwiki
[p]load thrillwiki
```

Every command works as a prefix command (`[p]thrillwiki`, or the short `[p]tw`) and as a slash command under `/thrillwiki`. Run `[p]slash sync` once if the slash commands don't show up.

## Commands

| Command | What it shows |
| --- | --- |
| `[p]tw park <name>` | Location, status, operator, ride and coaster counts, rating and a photo. |
| `[p]tw ride <name>` | Type, status, opening date, manufacturer, model, height, drop, length, speed, inversions and rating. Also answers to `attraction` and `coaster`. |
| `[p]tw company <name>` | Roles, founding year, ride count, rating and website for a manufacturer, designer, operator or owner. |
| `[p]tw waits <park>` | Today's hours and the 20 longest posted waits, plus how many rides are down. Also answers to `live`. |
| `[p]tw stats` | Site-wide counts for parks, attractions, coasters, photos and reviews. |

Each search shows the best match and lists up to five other matches in the footer, so if you got Steel Venom when you wanted Steel Vengeance you can see the right name and search again. Every embed links back to the page on ThrillWiki.

Heights and speeds are stored in metric on ThrillWiki. The cog shows metric with imperial in brackets, like `62.48 m (205 ft)`.

Live wait times come from [ThemeParks.wiki](https://themeparks.wiki/) through ThrillWiki, and the embed credits them. Parks they don't cover get a short "no live data" reply. Outside opening hours you'll see the hours with no waits, which is correct.

## Data

The cog stores nothing about users or servers. The only network traffic is read-only `GET` requests to `https://www.thrillwiki.com/api/v1/`.
