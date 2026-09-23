# Jev emoji

An [Omarchy](https://omarchy.org/) emoji picker that uses [Jev](https://docs.typesafe.ai/introduction).

You type words. Jev scores every emoji. Scores under 50% are hidden. The rest are sorted with the highest score first. Press Enter to paste the emoji into the app you were using.

## Install

You need Omarchy, Python 3, and a network connection.

```bash
omarchy plugin add https://github.com/nun/jev-emoji.git --enable
```

The first time you open it, paste a TypeSafe API key and press Enter.

Get a key from the [TypeSafe quick start](https://docs.typesafe.ai/introduction/quickstart). The key is saved on your computer in `~/.config/jev-emoji/api-key`. Only your user can read that file. It is not part of this repo.

You can also set `TYPESAFE_API_KEY` in the environment that starts the Omarchy shell.

## Open it

From a terminal:

```bash
omarchy-shell shell toggle jev.emoji
```

To use the normal emoji key, add this to `~/.config/hypr/bindings.lua`:

```lua
hl.unbind("SUPER + CTRL + E")
o.bind("SUPER + CTRL + E", "Jev emoji", "omarchy-shell shell toggle jev.emoji")
```

`Super + Ctrl + E` was the built-in emoji picker. The lines above replace that key.

To show it in the Omarchy menu, add this to `~/.config/omarchy/extensions/omarchy-menu.jsonc`:

```jsonc
"trigger.emoji": {
  "label": "Jev emoji",
  "description": "Search by meaning",
  "action": "omarchy-shell shell toggle jev.emoji"
}
```

Then search for `jev` or `emoji` with **Super + Space**.

To turn the built-in picker off:

```bash
omarchy plugin disable omarchy.emojis
```

## Update

```bash
omarchy plugin update jev.emoji
```

## How a search works

Each search sends the words you typed to Jev, once for every emoji. Jev returns a probability from 0 to 1. This plugin keeps the emojis at 0.5 or higher and sorts them from high to low.

That call uses your TypeSafe account. A short search still asks about the full emoji list, in a few parallel requests.
