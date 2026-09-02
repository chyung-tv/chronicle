# Play Out — design system

Locked from UI/UX Pro Max search (editorial-grid-magazine, dark OLED, theater/cinema palette structure, Chinese Traditional pairing). Applied as **coastal literary / harbor noir**, not SaaS Swiss or neon cyberpunk.

## Product

Sealed-canon story simulation. Writer's room, not a dashboard landing page.

## Pattern

App shell: masthead + run strip, Stage (map), Chronicle (tape + chapters), Cast (person + diary), God rail (inject / steer). CTA is 演一步 / 演完今日.

## Style

Editorial Grid / Magazine on a dark coastal field.

- Asymmetric hierarchy: Stage and Chronicle outweigh Cast
- God rail is visually separate from reading
- High contrast paper-on-sea, not neon
- Subtle 150–250ms transitions; respect `prefers-reduced-motion`

## Color

| Token | Hex | Role |
| --- | --- | --- |
| `--bg` | `#0F2429` | sea-deep background |
| `--bg-raised` | `#163038` | masthead / god rail |
| `--card` | `#1B333B` | panels |
| `--ink` | `#E8DCC4` | paper foreground |
| `--ink-dim` | `#C4B598` | secondary text |
| `--foam` | `#8BA8A6` | labels, edges, primary chrome |
| `--gold` | `#C4A574` | steer / spotlight |
| `--rust` | `#A34A3A` | kill, destructive |
| `--ok` | `#6B9A78` | succeeded |
| `--border` | `#3A5A62` | hairlines |
| `--on-paper` | `#1C1712` | text on chapter paper |

On-accent for gold buttons: `#0F2429`. Destructive on-color: `#E8DCC4`.

## Typography

Chinese Traditional pairing from the skill:

- Headings / story: **Noto Serif TC** (400/500/600/700)
- Chrome labels: **Noto Sans TC** (400/500/700), small-caps tracking on section titles

```
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@400;500;700&family=Noto+Serif+TC:wght@400;500;600;700&display=swap');
```

Latin editorial fallback: Cormorant Garamond / Libre Baskerville only if Noto is missing.

## Effects

- Hover 200ms, no parallax, no bounce
- Focus ring: `--foam` 2px
- `cursor: pointer` on controls
- No emoji icons

## Anti-patterns

AI purple/pink gradients, Swiss-pink CTA (`#EC4899`), matrix neon, three equal-weight columns, landing-page hero, emoji as icons.
