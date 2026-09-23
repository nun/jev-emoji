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

```bash
omarchy-shell shell toggle jev.emoji
```

## Update

```bash
omarchy plugin update jev.emoji
```

## How a search works

Each search sends the words you typed to Jev, once for every emoji. Jev returns a probability from 0 to 1. This plugin keeps the emojis at 0.5 or higher and sorts them from high to low.

That call uses your TypeSafe account. A short search still asks about the full emoji list, in a few parallel requests.
