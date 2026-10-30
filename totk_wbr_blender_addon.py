bl_info = {
    "name": "TotK WBR Blur Writer",
    "author": "Catzy123",
    "version": (1, 0, 0),
    "blender": (3, 3, 0),
    "location": "View3D > Sidebar > TotK Blur",
    "description": "Bake the active action's sword swing into a TotK .wbr blur file.",
    "category": "Animation",
}

import struct
from dataclasses import dataclass
from pathlib import Path

import bpy
from bpy.app.handlers import persistent
from bpy.props import IntProperty, PointerProperty, StringProperty


NAME_LEN = 0x40
HEADER_LEN = NAME_LEN + 12  # name, start frame, end frame, segment count
# equip bone trans + rot, then swing base bone trans + rot
SEGMENT = struct.Struct("<12f")
SUBSTEPS = 10  # segments per frame

DEFAULT_EQUIP_BONE = "Weapon_R"
DEFAULT_SWING_BONE = "Spine_2"

SWING_BONE_INFO = (
    "If you edit someone other than Link, check their "
    "Component/SwordBlurParam inside their actor pack. If it has no "
    "SwingBaseBone, the game uses Spine_1. You can also add your own, "
    "like SwingBaseBone: Clavicle_R, just pick the same bone here."
)
EQUIP_BONE_INFO = (
    "The equip bone is the bone the sword is held by. It can be changed if it "
    "isn't the right bone, or if you just want to fake a sword trail, like "
    "putting the trail on a different bone just for the visuals."
)

_baking = False


@dataclass
class BlurEntry:
    anim_name: str
    start_frame: int
    end_frame: int
    segments: list  # 12-float tuples laid out like SEGMENT


def check_raw_wbr(path):
    name = path.name.lower()
    if name.endswith(".zs"):
        raise ValueError("This addon only edits raw .wbr files. Decompress the .zs first.")
    if not name.endswith(".wbr"):
        raise ValueError("The selected file must be a raw .wbr file.")


def read_wbr(path):
    data = path.read_bytes()
    entries = []
    try:
        (count,) = struct.unpack_from("<I", data, 0)
        for offset in struct.unpack_from(f"<{count}I", data, 4):
            name = data[offset:offset + NAME_LEN].split(b"\0", 1)[0].decode("utf-8", "ignore")
            start, end, seg_count = struct.unpack_from("<3I", data, offset + NAME_LEN)
            first = offset + HEADER_LEN
            segments = [SEGMENT.unpack_from(data, first + i * SEGMENT.size) for i in range(seg_count)]
            entries.append(BlurEntry(name, start, end, segments))
    except struct.error:
        raise ValueError(f"{path.name} is truncated or isn't a WBR file.") from None
    return entries


def write_wbr(path, entries):
    table = bytearray(struct.pack("<I", len(entries)))
    body = bytearray()
    data_start = 4 + 4 * len(entries)
    for entry in entries:
        name = entry.anim_name.encode("utf-8")
        if len(name) >= NAME_LEN:
            raise ValueError(f"Animation name is too long for WBR: {entry.anim_name}")
        table += struct.pack("<I", data_start + len(body))
        body += name.ljust(NAME_LEN, b"\0")
        body += struct.pack("<3I", entry.start_frame, entry.end_frame, len(entry.segments))
        for seg in entry.segments:
            body += SEGMENT.pack(*seg)
    # write next to it first so a crash mid-write can't leave a half-written wbr
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(table + body)
    tmp.replace(path)


def put_entry(entries, new_entry):
    """Swap new_entry in where its name already exists (dropping duplicates), else append it."""
    out = []
    placed = False
    for entry in entries:
        if entry.anim_name != new_entry.anim_name:
            out.append(entry)
        elif not placed:
            out.append(new_entry)
            placed = True
    if not placed:
        out.append(new_entry)
    return out


def rotation_vector(matrix):
    # axis * angle, with the quaternion flipped so its biggest component is positive
    q = matrix.to_quaternion()
    if max(q, key=abs) < 0.0:
        q = -q
    axis, angle = q.to_axis_angle()
    return axis * angle


def find_armature(context):
    candidates = [getattr(context, "object", None), getattr(context, "active_object", None)]
    candidates += getattr(context, "selected_objects", None) or []
    candidates.append(bpy.data.objects.get("Armature"))
    for obj in candidates:
        if obj is not None and obj.type == "ARMATURE":
            return obj
    return next((obj for obj in bpy.data.objects if obj.type == "ARMATURE"), None)


def active_action(armature):
    anim = armature.animation_data if armature else None
    return anim.action if anim else None


def sync_from_active_action(context, settings, force=False):
    action = active_action(find_armature(context))
    if action is None:
        return
    if not force and action.name == settings.last_synced_active_action:
        return
    start, end = action.frame_range
    settings.action_name = action.name
    settings.start_frame = max(0, round(start))
    settings.end_frame = round(end)
    settings.last_synced_active_action = action.name


def bake_entry(context, settings):
    global _baking

    armature = find_armature(context)
    if armature is None:
        raise ValueError("No armature found in the current scene.")

    action = active_action(armature)
    anim_name = settings.action_name.strip() or (action.name if action else "")
    if not anim_name:
        raise ValueError("Action name is empty. Fill it in or sync from the active action.")

    start, end = settings.start_frame, settings.end_frame
    if end <= start:
        raise ValueError("End frame must be greater than start frame.")

    equip = armature.pose.bones.get(settings.equip_bone)
    swing = armature.pose.bones.get(settings.swing_base_bone)
    if equip is None:
        raise ValueError(f"Could not find equip bone: {settings.equip_bone}")
    if swing is None:
        raise ValueError(f"Could not find swing base bone: {settings.swing_base_bone}")

    scene = context.scene
    old_frame, old_subframe = scene.frame_current, scene.frame_subframe
    segments = []
    _baking = True
    try:
        for frame in range(start, end):
            for step in range(SUBSTEPS):
                scene.frame_set(frame, subframe=step / SUBSTEPS)
                equip_mat = equip.matrix.copy()
                swing_mat = swing.matrix.copy()
                segments.append((
                    *equip_mat.translation, *rotation_vector(equip_mat),
                    *swing_mat.translation, *rotation_vector(swing_mat),
                ))
    finally:
        scene.frame_set(old_frame, subframe=old_subframe)
        _baking = False

    return BlurEntry(anim_name, start, end, segments)


class TOTKBlurSettings(bpy.types.PropertyGroup):
    action_name: StringProperty(
        name="Action Name",
        description="Name of the WBR entry to write",
    )
    start_frame: IntProperty(
        name="Start Frame",
        description="First frame to bake (inclusive)",
        default=0,
        min=0,
    )
    end_frame: IntProperty(
        name="End Frame",
        description="Frame to stop at (exclusive)",
        default=1,
    )
    wbr_path: StringProperty(
        name="WBR File",
        description="Raw .wbr file to update",
        subtype="FILE_PATH",
    )
    swing_base_bone: StringProperty(
        name="Swing Base Bone",
        description=SWING_BONE_INFO,
        default=DEFAULT_SWING_BONE,
    )
    equip_bone: StringProperty(
        name="Equip Bone",
        description=EQUIP_BONE_INFO,
        default=DEFAULT_EQUIP_BONE,
    )
    last_synced_active_action: StringProperty(options={"HIDDEN"})


class TOTK_OT_sync_active_action(bpy.types.Operator):
    bl_idname = "totk.sync_active_action"
    bl_label = "Use Active Action"
    bl_description = "Fill the action name and frame range from the active armature action"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        sync_from_active_action(context, context.scene.totk_blur_settings, force=True)
        return {"FINISHED"}


class TOTK_OT_blur_info(bpy.types.Operator):
    bl_idname = "totk.blur_info"
    bl_label = "Info"
    bl_options = {"INTERNAL"}

    text: StringProperty(options={"HIDDEN", "SKIP_SAVE"})

    @classmethod
    def description(cls, context, properties):
        return properties.text

    def execute(self, context):
        self.report({"INFO"}, self.text)
        return {"FINISHED"}


class TOTK_OT_generate_wbr(bpy.types.Operator):
    bl_idname = "totk.generate_wbr"
    bl_label = "Generate"
    bl_description = "Bake the blur entry and write it straight into the selected WBR file"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return find_armature(context) is not None

    def execute(self, context):
        settings = context.scene.totk_blur_settings
        if not settings.wbr_path.strip():
            self.report({"ERROR"}, "Select a WBR file first.")
            return {"CANCELLED"}

        # the file browser can hand back "//relative" paths
        path = Path(bpy.path.abspath(settings.wbr_path)).expanduser()
        try:
            check_raw_wbr(path)
            if not path.is_file():
                raise ValueError(f"WBR file not found: {path}")
            entries = read_wbr(path)
            entry = bake_entry(context, settings)
            write_wbr(path, put_entry(entries, entry))
        except (ValueError, OSError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        if not settings.action_name.strip():
            settings.action_name = entry.anim_name
        self.report({"INFO"}, f"Wrote {entry.anim_name} into {path.name}")
        return {"FINISHED"}


def draw_bone_row(layout, settings, prop, armature, info):
    row = layout.row(align=True)
    if armature is not None:
        row.prop_search(settings, prop, armature.data, "bones")
    else:
        row.prop(settings, prop)
    row.operator("totk.blur_info", text="", icon="INFO").text = info


class TOTK_PT_blur_writer(bpy.types.Panel):
    bl_label = "WBR Blur Writer"
    bl_idname = "TOTK_PT_blur_writer"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "TotK Blur"

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        settings = context.scene.totk_blur_settings
        armature = find_armature(context)
        action = active_action(armature)

        layout.label(text=f"Active Action: {action.name if action else 'None'}")

        row = layout.row(align=True)
        try:
            # lets you type any name, not just existing actions (Blender 3.3+)
            row.prop_search(settings, "action_name", bpy.data, "actions",
                            text="Action Name", results_are_suggestions=True)
        except TypeError:
            row.prop(settings, "action_name")
        row.operator("totk.sync_active_action", text="", icon="FILE_REFRESH")

        row = layout.row(align=True)
        row.prop(settings, "start_frame")
        row.prop(settings, "end_frame")

        draw_bone_row(layout, settings, "swing_base_bone", armature, SWING_BONE_INFO)
        draw_bone_row(layout, settings, "equip_bone", armature, EQUIP_BONE_INFO)

        layout.prop(settings, "wbr_path")

        row = layout.row()
        row.enabled = bool(
            settings.wbr_path.strip()
            and (settings.action_name.strip() or action)
            and settings.equip_bone
            and settings.swing_base_bone
            and settings.end_frame > settings.start_frame
        )
        row.operator("totk.generate_wbr", icon="FILE_TICK")


@persistent
def on_depsgraph_update(_scene, _depsgraph):
    if _baking:
        return
    scene = getattr(bpy.context, "scene", None)
    if scene is None or not hasattr(scene, "totk_blur_settings"):
        return
    try:
        sync_from_active_action(bpy.context, scene.totk_blur_settings)
    except Exception:
        # runs on every depsgraph update, a traceback here would just spam the console
        pass


classes = (
    TOTKBlurSettings,
    TOTK_OT_sync_active_action,
    TOTK_OT_blur_info,
    TOTK_OT_generate_wbr,
    TOTK_PT_blur_writer,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.totk_blur_settings = PointerProperty(type=TOTKBlurSettings)

    # context is restricted while Blender is starting up, the handler catches up later
    scene = getattr(bpy.context, "scene", None)
    if scene is not None:
        sync_from_active_action(bpy.context, scene.totk_blur_settings, force=True)

    if on_depsgraph_update not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(on_depsgraph_update)


def unregister():
    if on_depsgraph_update in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(on_depsgraph_update)
    del bpy.types.Scene.totk_blur_settings
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
