# Credits

## The game

[The Elder Scrolls V: Skyrim](https://elderscrolls.bethesda.net/en/skyrim) is © ZeniMax Media Inc. and published by
Bethesda Softworks. All rights to the game and its content belong to them, including everything here taken from it:

- the collectible placements, scripts and quest data, read out of `Skyrim.esm`, `Update.esm`, `Dawnguard.esm`,
  `HearthFires.esm` and `Dragonborn.esm` in Skyrim, Skyrim Special Edition and Skyrim VR
- the dragon emblem in the masthead and the collectible icons, rendered from the game's own meshes and textures
- the night sky behind the page, from the skills menu's textures
- the local map images in `docs/img/local`, rendered from the Special Edition's world data, meshes and textures

This is a fan project and is not affiliated with or endorsed by Bethesda Softworks or ZeniMax Media.

## Maps

| Work | Author | Used for |
|---|---|---|
| [Skyrim, Solstheim, Soul Cairn and Forgotten Vale maps](https://en.uesp.net/wiki/Skyrim:Maps) | The [UESP](https://en.uesp.net/) and its contributors | The map tiles |

## Reference

From the [UESP](https://en.uesp.net/), by its contributors, under
[CC BY-SA 2.5](https://creativecommons.org/licenses/by-sa/2.5/):

- [Save File Format](https://en.uesp.net/wiki/Skyrim_Mod:Save_File_Format), [Papyrus](https://en.uesp.net/wiki/Skyrim_Mod:Save_File_Format/Papyrus)
  and [Change Flags](https://en.uesp.net/wiki/Skyrim_Mod:ChangeFlags), which the save reader follows
- [Dragon Shouts](https://en.uesp.net/wiki/Skyrim:Dragon_Shouts) and the pages for each shout, for the words taught
  during quests
- [The Litany of Larceny](https://en.uesp.net/wiki/Skyrim:The_Litany_of_Larceny), [Lost Legacy](https://en.uesp.net/wiki/Skyrim:Lost_Legacy),
  [The Kagrumez Gauntlet](https://en.uesp.net/wiki/Skyrim:The_Kagrumez_Gauntlet) and
  [Miscellaneous Items](https://en.uesp.net/wiki/Skyrim:Miscellaneous_Items), checked against the game data

## Local maps

`tools/localmap.py` reproduces the look of the local maps drawn by the game's engine, © Bethesda Softworks, from the
game's own shaders and data. The images come from the Special Edition and may not resemble the 2011 edition's maps.
Deliberate differences from the game:

- everything is drawn as explored, with no fog of war
- secret room panels marked Localmap_Hide_Secret are hidden, so hidden rooms show
- land is lit at noon in the climate's most likely weather, where the game uses the current time and weather
- no point lights, and water is drawn as flat black
- the backdrop is a flat colour, not the menu behind the map

## Typefaces

Both under the [SIL Open Font License 1.1](https://openfontlicense.org).

| Face | Copyright |
|---|---|
| Barlow Condensed | The Barlow Project Authors, served by [Google Fonts](https://fonts.google.com/specimen/Barlow+Condensed) |
| OpenDyslexic | Abbie Gonzalez ([opendyslexic.org](https://opendyslexic.org)) |

## Tools

| Work | Author | Used for |
|---|---|---|
| [Pillow](https://python-pillow.github.io) | Jeffrey A. Clark and contributors | Converting game textures and map tiles, and drawing the icons |
| [NumPy](https://numpy.org) | NumPy Developers | Rendering the game meshes and fitting the maps |
| [python-lz4](https://github.com/python-lz4/python-lz4) | Jonathan Underwood and contributors | Reading Skyrim Special Edition's archives |
