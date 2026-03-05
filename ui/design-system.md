# Design System

This document defines the visual design language for the Netherbrain Web UI.
All UI components should follow these conventions. The source of truth for
token values is `src/index.css`.

## Design Philosophy

1. **Clean and Minimal** -- Reduce visual noise, focus on content.
2. **Natural Warmth** -- Warm backgrounds and earthy brand colors (never cold grey).
3. **Soft Rounded** -- Large border radius for a friendly, modern feel.
4. **Subtle Depth** -- Shadows and transparency for visual hierarchy.
5. **Chatbot-first Typography** -- Comfortable reading in conversational context.

## Color System

All colors are defined as CSS custom properties in oklch color space.
Both light and dark themes use the same hue family (hue ~85 for neutrals,
~145 for brand green) to maintain warmth.

### Brand Color

Earthy green, used for primary actions, active states, and brand accents.

| Token       | Light                           | Dark                            |
| ----------- | ------------------------------- | ------------------------------- |
| `--primary` | `oklch(0.44 0.05 145)` ~#55644a | `oklch(0.62 0.08 145)` brighter |

### Surface Hierarchy

| Surface    | Light                    | Dark                       | Usage                   |
| ---------- | ------------------------ | -------------------------- | ----------------------- |
| background | warm beige (L=0.965)     | warm charcoal (L=0.155)    | Page background         |
| card       | warm white (L=0.995)     | warm dark (L=0.195)        | Cards, popovers, inputs |
| sidebar    | near-white (L=0.99)      | slightly lighter (L=0.175) | Sidebar panel           |
| muted      | warm light grey (L=0.94) | warm dark grey (L=0.23)    | Muted backgrounds       |

### Opacity-based Patterns

Borders and subtle backgrounds use opacity rather than fixed shades:

| Usage           | Light     | Dark      | Tailwind class          |
| --------------- | --------- | --------- | ----------------------- |
| Standard border | black/8%  | white/8%  | `border-border`         |
| Input border    | black/10% | white/12% | `border-input`          |
| Sidebar border  | black/6%  | white/6%  | `border-sidebar-border` |

### Text Hierarchy

Text color is handled via semantic tokens, all with warm undertones (hue=85):

| Level     | Token              | Light L | Dark L | Usage                        |
| --------- | ------------------ | ------- | ------ | ---------------------------- |
| Primary   | `foreground`       | 0.14    | 0.92   | Body text, headings          |
| Secondary | `muted-foreground` | 0.44    | 0.58   | Labels, timestamps, metadata |

For finer granularity, use Tailwind opacity: `text-foreground/80`, `text-muted-foreground/60`.

### Status Colors

| Status      | Token         | Value                                                  |
| ----------- | ------------- | ------------------------------------------------------ |
| Destructive | `destructive` | red, lighter in dark mode                              |
| Success     | `primary`     | Use brand green for success                            |
| Warning     | --            | `text-amber-500 dark:text-amber-400` (direct Tailwind) |

## Typography

### Font Stack

```
"Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
"Helvetica Neue", Arial, sans-serif
```

### Global Settings

| Property              | Value            |
| --------------------- | ---------------- |
| Base line-height      | 1.6              |
| Letter spacing        | -0.011em         |
| Font feature settings | `"cv11", "ss01"` |
| Font smoothing        | antialiased      |

### Chat Prose Scale

The `.chat-prose` class defines chatbot-optimised typography (defined in
`src/index.css` `@layer components`). It uses a tighter heading scale
than documentation prose:

| Element | Size             | Weight   | Spacing         |
| ------- | ---------------- | -------- | --------------- |
| Body    | 0.9375rem (15px) | normal   | leading-relaxed |
| h1      | text-lg (18px)   | semibold | mt-5 mb-2       |
| h2      | text-base (16px) | semibold | mt-4 mb-2       |
| h3      | 0.9375rem        | semibold | mt-3 mb-1.5     |
| h4      | 0.9375rem        | medium   | mt-3 mb-1       |
| p       | inherited        | normal   | my-2            |
| li      | inherited        | normal   | my-0.5          |

## Spacing and Layout

### Border Radius

Base radius: `0.75rem`. All derived sizes use calc:

| Token      | Value        | Tailwind      | Usage                       |
| ---------- | ------------ | ------------- | --------------------------- |
| radius-sm  | radius - 4px | `rounded-sm`  | Small badges                |
| radius-md  | radius - 2px | `rounded-md`  | Buttons, inputs             |
| radius-lg  | 0.75rem      | `rounded-lg`  | Cards, code blocks          |
| radius-xl  | radius + 4px | `rounded-xl`  | Tool cards, sidebar items   |
| radius-2xl | radius + 8px | `rounded-2xl` | Message bubbles, chat input |

### Component-specific Radius

| Component           | Class                       |
| ------------------- | --------------------------- |
| User message bubble | `rounded-2xl rounded-br-md` |
| Chat input wrapper  | `rounded-2xl`               |
| Tool call card      | `rounded-xl`                |
| Code block          | `rounded-xl`                |
| Sidebar conv item   | `rounded-xl`                |
| Login card          | `rounded-2xl`               |
| Send/stop button    | `rounded-xl`                |

### Message Layout

- Max width: `max-w-3xl` centered.
- User messages: right-aligned, `max-w-[80%]`.
- Assistant messages: left-aligned, `max-w-[90%]`.
- Vertical padding per message: `py-3`.
- Avatar: `h-7 w-7` rounded-full with `bg-primary/10`.

## Shadow System

Minimal shadows for subtle depth:

| Usage               | Class                             |
| ------------------- | --------------------------------- |
| User message bubble | `shadow-sm`                       |
| Tool call card      | `shadow-sm`                       |
| Code block          | `shadow-sm`                       |
| Chat input wrapper  | `shadow-sm`, `shadow-md` on focus |
| Login card          | `shadow-md`                       |

## Animation

- Theme transitions: none (instant switch).
- Streaming cursor: `animate-pulse` on a brand-colored bar.
- Expand/collapse chevrons: `transition-transform duration-200`.
- Hover states: `transition-colors` (default duration).

## Code Highlighting

Uses Shiki with warm themes:

| Mode  | Shiki Theme   |
| ----- | ------------- |
| Light | vitesse-light |
| Dark  | vitesse-dark  |

Code blocks have a header bar showing language name and copy button,
wrapped in a card-like container (`bg-card border shadow-sm`).

Inline code uses `bg-muted/80 text-foreground/85` with `rounded-md`.

## Scrollbar

Custom WebKit scrollbar: 6px wide, transparent track, warm opacity thumb.

| State  | Light     | Dark      |
| ------ | --------- | --------- |
| Normal | black/12% | white/12% |
| Hover  | black/20% | white/20% |

## Selection

Text selection uses brand green at low opacity:

- Light: `oklch(0.44 0.05 145 / 20%)`
- Dark: `oklch(0.62 0.08 145 / 25%)`

## Component Patterns

### Chat Input

Card-style wrapper (not just a bordered textarea): `bg-card rounded-2xl border shadow-sm` with `shadow-md` and `border-primary/20` on focus-within.
Textarea is transparent, no visible border. Send button uses primary color.

### Message Bubbles

- **User**: Brand-colored background (`bg-primary text-primary-foreground`),
  right-aligned with one softened corner (`rounded-br-md`).
- **Assistant**: No background, left-aligned with bot avatar. Content renders
  via `.chat-prose`.

### Tool Call Cards

Collapsible card with status icon. Uses `bg-card` with subtle border and
shadow. Status icons use brand green (running/complete) or semantic colors
(retry: amber, cancel: destructive).

### Sidebar

White/near-white panel in light mode, slightly elevated dark surface in
dark mode. Active conversation uses `sidebar-accent` (subtle green tint).
Footer has theme toggle, settings, and logout.

### Attachments

**Preview strip**: Horizontal scroll container inside the input wrapper, above
the textarea. Only visible when attachments are present. Uses `gap-2` spacing.

**Image thumbnail**: `h-16 w-16 rounded-lg object-cover` with a small
remove button overlay (`absolute -top-1.5 -right-1.5 h-5 w-5 rounded-full bg-foreground/80 text-background`). Shows local preview via `URL.createObjectURL`.

**File chip**: `bg-muted rounded-lg px-3 py-2 text-sm` with file type icon
(from lucide-react), truncated filename (`max-w-[140px] truncate`), and
human-readable size in muted text. Remove button inline.

**Drop zone highlight**: On drag-over, input wrapper transitions to
`border-primary border-dashed bg-primary/5`.

**User message attachments (history)**: Image thumbnails render inline
below the text (`rounded-lg max-h-48 cursor-pointer`). File/URL parts
render as compact badges (`bg-muted/60 rounded-md px-2 py-1 text-xs`).

### Login / Auth Pages

Centered card on page background. Brand icon (Bot) with `bg-primary/10`.
All inputs and buttons use `rounded-xl`.
