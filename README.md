# wbr-tools

Tools for making custom weapon trails in Tears of the Kingdom.

The white blur that follows the sword when Link swings it comes from `Effect/Blur/Player.wbr.zs`. That file stores how the sword and Link's upper body move during every swing, and the game draws the trail from that. So if you make a new attack animation, or change an existing one, the trail won't line up anymore unless you update the .wbr too. That's what this is for.

It isn't only for Link. Enemies and NPCs that swing weapons have their own .wbr files, so it works on any character with a weapon trail. And it works for spears too, for their thrust trails.

There are two tools in here:

- **WBR Blur Writer**: a Blender add-on that takes your animation and writes the trail data straight into a .wbr file
- **WBR Convert**: a small converter that turns a .wbr into a readable .yaml and back, so you can look at or edit entries by hand

This is for TotK, but from what I saw BotW's blur files use the same position and rotation data. So if you understand the format, you can copy the right values over into BotW's files too.

![Sword Blur Image](https://files.gamebanana.com/bitpit/screenshot_3163_.png)

---

## What you need

- Blender 3.3 or newer (I use 4.5)
- Link's model with his animations imported into Blender (or any other character). The armature needs the `Weapon_R` and `Spine_2` bones (or whatever bones you pick, more on that below)
- A **decompressed** `Player.wbr`. Both tools only work with raw .wbr files, so decompress `Player.wbr.zs` first with whatever totk zs tool you use, if you don't have one then just use this [Totk-ZstdTool](https://github.com/TotkMods/Totk-ZstdTool), and compress it back to `.zs` when you're done
- For other characters it works the same way, they just have their own file named after the actor in the same folder, like `Effect/Blur/Enemy_Lynel_Junior.wbr.zs` or `Effect/Blur/Npc_ZoraFencer.wbr.zs`

---

## WBR Blur Writer (Blender add-on)

### Installing

1. Download `totk_wbr_blender_addon.py` from the releases
2. In Blender go to Edit > Preferences > Add-ons
3. Blender 4.2 and newer: click the little arrow at the top right and pick **Install from Disk**. Older versions: click **Install...**
4. Select the .py file and tick the checkbox to enable it

You'll find it in the 3D viewport sidebar (press N) under the **TotK Blur** tab.

![Add-on Image](https://files.gamebanana.com/bitpit/screenshot_2026-10-30_182509.png)

### How to use it

1. Select Link's armature and make the animation you want active. The add-on picks up the active action by itself and fills in the name and frame range
2. Check the **Action Name**. This is the name the entry gets in the .wbr, so it has to match the animation name the game uses (like `Sword_Attack_S1`)
3. Set the **Start Frame** and **End Frame**. The end frame itself isn't baked, so 0 to 5 bakes frames 0, 1, 2, 3 and 4. This should cover the part of the swing where the trail actually shows
4. Pick your **WBR File** (the raw Player.wbr)
5. Hit **Generate**

Note: The Blurs do not get shown in Blender, only in game.

If the file already has an entry with that name it gets replaced, otherwise it gets added. Every frame is sampled 10 times, the same as the vanilla files.

Heads up: the Action Name field is just the name that gets written. The add-on always bakes whatever action is *currently active* on the armature, even if you pick a different one in that dropdown.

### Swing Base Bone and Equip Bone

- **Swing Base Bone** (default `Spine_2`): the body bone the swing is measured from. If you're doing this for someone other than Link, check their `Component/SwordBlurParam` inside their actor pack to see which bone they use. If there's no `SwingBaseBone` in there, the game uses `Spine_1`. Link's own file sets `Spine_2`, that's why the add-on defaults to that

  You can also add your own `SwingBaseBone` to that file if you want a different bone. For example the vanilla `Enemy_Zonau_Golem_Junior` (Soldier Construct) one is just this:

  ```yaml
  SwingBaseBone: Clavicle_R
  ```

  Just make sure you pick the same bone in the add-on when you bake, otherwise the trail won't line up
- **Equip Bone** (default `Weapon_R`): the bone the weapon is held by. You can change it if that isn't the right bone, or if you want to fake a trail on something else, like putting the effect on a different bone just for the looks

Both fields are dropdowns with every bone in the armature.

### Making the trail actually show up

The .wbr only stores the motion. Whether the trail is visible is decided by the **WeaponBlur** event in the animation's AnimationEvent file. If that event isn't there, or its frames are wrong, you won't see a trail no matter what's in the .wbr.

The game connects the two by name, so the AnimationEvent file has to be called the same as the animation file:

| Animation | AnimationEvent |
|---|---|
| `Model/Player_Animation.anim.bfres.zs` | `AnimationEvent/Animation/Player_Animation.anim.baev.zs` |

Inside the .baev, each animation can have WeaponBlur events with a frame range, and the trail only shows during those frames. For example, if you generated frames 10 to 40 in the .wbr, but the WeaponBlur event says frames 10 to 20 and then again 35 to 40, then that's exactly when you'll see it. Frames 20 to 35 stay invisible even though the .wbr has data for them.

So the .wbr range should cover every frame where the WeaponBlur event turns the trail on.

You can also add WeaponBlur events for new animations. The animation names are stored as hashes inside the .baev, so use the [Asb/Baev Tool](https://gamebanana.com/tools/21706) to get the hash for your animation name.

![Baev Image](https://files.gamebanana.com/bitpit/screenshot_2026-10-30_031210.png)

The image is basically a single event, even if it looks like 2 different ones. The top part is the animation (its name hash), and the WeaponBlur event is listed right under it.

Also good to know is that the Weapon trails also show up during cutscenes/events, not just normal gameplay

---

## WBR Convert

Drag a `.wbr` onto `WBR Convert.exe` and you get a `.yaml` next to it. Drag the `.yaml` back on and you get the `.wbr` again. You can drop more than one file at once.

A few things it does:

- **Removes duplicates.** Vanilla Player.wbr has about 90 entries that are exact copies of other ones. They're just bloat, so they get dropped when you convert to yaml (won't break anything in game).
- **Tells you what's wrong.** If something in your yaml is broken it tells you exactly where, like `Sword_Attack_S1 segment 2: equip_rot needs 3 numbers`

It doesn't do .zs files, decompress them first.

### What the yaml looks like

```yaml
- anim_name: Sword_Attack_S1
  start_frame: 0
  end_frame: 5
  segments:
  - equip_pos: [-0.5821400284767151, 1.21029794216156, 0.6045070290565491]
    equip_rot: [2.753530979156494, -0.19061000645160675, -1.730774998664856]
    swing_base_pos: [-0.06515700370073318, 0.9607279896736145, 0.02544100023806095]
    swing_base_rot: [2.315213918685913, 1.2058559656143188, 1.1377509832382202]
  - ...
```

- `equip_pos` / `equip_rot`: where the equip bone is and how it's rotated
- `swing_base_pos` / `swing_base_rot`: same thing for the swing base bone

There are 10 segments per frame, so 0 to 5 gives you 50 of them.

### Linux / Mac

The exe is Windows only, but the script itself works anywhere with Python 3.7 or newer:

```
pip install pyyaml
python3 wbr_convert.py Player.wbr
```

### Building the exe yourself

```
pip install pyyaml pyinstaller
pyinstaller "WBR Convert.spec"
```

The exe ends up in the `dist` folder.

---

## Credits

Huge thanks to [**Dt12345**](https://github.com/dt-12345) for reverse engineering the .wbr format in the first place. None of this would exist without him.
