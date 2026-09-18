extends Node2D

const STATE_PATH := "user://world.json"
const TILE := 32
const MOVE_SPEED := 220.0

var state: Dictionary = {}
var player := Vector2(480, 360)
var prompt := ""
var message := ""
var area_id := "oaks_lab"
var worldgen_path := ""
var interaction_cooldown := 0.0

func _ready() -> void:
    worldgen_path = _find_worldgen()
    if Input.is_key_pressed(KEY_F5):
        _reset_save()
    if not FileAccess.file_exists(STATE_PATH):
        if not _run_worldgen(["bootstrap", "--seed", "42", "--output", ProjectSettings.globalize_path(STATE_PATH)]):
            _fallback_bootstrap()
    _load_state()
    queue_redraw()

func _process(delta: float) -> void:
    interaction_cooldown = maxf(0.0, interaction_cooldown - delta)
    var dir := Input.get_vector("move_left", "move_right", "move_up", "move_down")
    player += dir * MOVE_SPEED * delta
    player.x = clampf(player.x, 40.0, 920.0)
    player.y = clampf(player.y, 80.0, 500.0)

    if Input.is_action_just_pressed("interact") and interaction_cooldown <= 0.0:
        interaction_cooldown = 0.18
        _interact()

    if Input.is_key_pressed(KEY_F5):
        _reset_save()
        _run_worldgen(["bootstrap", "--seed", "42", "--output", ProjectSettings.globalize_path(STATE_PATH)])
        _load_state()

    queue_redraw()

func _draw() -> void:
    draw_rect(Rect2(0, 0, 960, 540), Color("111820"))
    draw_rect(Rect2(18, 18, 924, 54), Color("202d3a"))
    var area: Dictionary = state.get("areas", {}).get(area_id, {})
    var title := "%s   |   challenge %.2f   |   badges %d" % [
        area.get("name", area_id),
        float(area.get("challenge", 1.0)),
        int(state.get("badges", 0))
    ]
    draw_string(ThemeDB.fallback_font, Vector2(36, 52), title, HORIZONTAL_ALIGNMENT_LEFT, -1, 24, Color.WHITE)

    if area_id == "oaks_lab":
        _draw_lab()
    else:
        _draw_generated(area)

    draw_circle(player, 11, Color("ffdf6b"))
    draw_circle(player + Vector2(3, -2), 3, Color("2a2a2a"))
    draw_string(ThemeDB.fallback_font, Vector2(26, 520), message if message != "" else "WASD/arrows move • E/Enter interact • F5 reset", HORIZONTAL_ALIGNMENT_LEFT, -1, 18, Color("d8e3ec"))

func _draw_lab() -> void:
    draw_rect(Rect2(250, 110, 460, 340), Color("d8d1ba"), true)
    draw_rect(Rect2(440, 425, 80, 25), Color("574637"), true)
    draw_rect(Rect2(340, 180, 80, 45), Color("86b7d1"), true)
    draw_rect(Rect2(540, 180, 80, 45), Color("d47777"), true)
    draw_string(ThemeDB.fallback_font, Vector2(336, 170), "OAK", HORIZONTAL_ALIGNMENT_LEFT, -1, 18, Color("111111"))
    draw_string(ThemeDB.fallback_font, Vector2(532, 170), "RIVAL", HORIZONTAL_ALIGNMENT_LEFT, -1, 18, Color("111111"))

func _draw_generated(area: Dictionary) -> void:
    draw_rect(Rect2(100, 105, 760, 350), Color("55724d"), true)
    draw_rect(Rect2(100, 325, 760, 70), Color("b89969"), true)
    draw_rect(Rect2(410, 105, 140, 120), Color("8e795b"), true)
    draw_rect(Rect2(690, 250, 90, 75), Color("7e654b"), true)
    draw_string(ThemeDB.fallback_font, Vector2(430, 165), "INN", HORIZONTAL_ALIGNMENT_LEFT, -1, 18, Color.WHITE)
    draw_string(ThemeDB.fallback_font, Vector2(680, 240), "GUIDE", HORIZONTAL_ALIGNMENT_LEFT, -1, 18, Color.WHITE)
    draw_rect(Rect2(820, 340, 40, 40), Color("dfd7ae"), true)
    draw_string(ThemeDB.fallback_font, Vector2(785, 330), "EAST →", HORIZONTAL_ALIGNMENT_LEFT, -1, 17, Color.WHITE)
    if _has_exit(area, "north_blocked"):
        draw_rect(Rect2(430, 105, 100, 14), Color("6a4138"), true)
        draw_string(ThemeDB.fallback_font, Vector2(376, 98), "DAMAGED ROAD", HORIZONTAL_ALIGNMENT_LEFT, -1, 17, Color("ffd6bf"))

func _interact() -> void:
    var area: Dictionary = state.get("areas", {}).get(area_id, {})
    if area_id == "oaks_lab":
        if player.distance_to(Vector2(380, 205)) < 95:
            if state.get("starter", null) == null:
                _pick_starter()
            else:
                message = "Oak: Your partner is %s." % String(state["starter"]).capitalize()
            return
        if player.distance_to(Vector2(580, 205)) < 95:
            if state.get("starter", null) == null:
                message = "Rival: Pick a Pokémon first."
            elif not bool(state.get("rival_defeated", false)):
                if _run_worldgen(["defeat-rival", "--state", ProjectSettings.globalize_path(STATE_PATH)]):
                    _load_state()
                    message = "Rival battle milestone complete. The south door is open."
            else:
                message = "Rival: Next time won't be so easy."
            return
        if player.y > 405 and absf(player.x - 480.0) < 95:
            _use_exit("south_door")
            return
        message = "Try Oak, your rival, or the south door."
    else:
        if player.x > 790 and player.y > 300:
            _use_exit("east_frontier")
            return
        if player.y < 145 and absf(player.x - 480.0) < 120 and _has_exit(area, "north_blocked"):
            message = "The north road is damaged. Something later may reopen it."
            return
        if player.distance_to(Vector2(730, 285)) < 90:
            message = "Guide: Routes ahead are generated, but they remember where you came from."
            return
        if player.x < 145 and player.y > 300:
            _use_exit("back")
            return
        message = "Explore the village. East continues; north is a future payoff."

func _pick_starter() -> void:
    var options := ["bulbasaur", "charmander", "squirtle"]
    var index := int(Time.get_ticks_msec() / 500) % options.size()
    var starter: String = options[index]
    if _run_worldgen(["choose-starter", "--state", ProjectSettings.globalize_path(STATE_PATH), "--starter", starter]):
        _load_state()
        message = "Oak: %s chose you. (Interact again to cycle by timing.)" % starter.capitalize()

func _use_exit(exit_id: String) -> void:
    var area: Dictionary = state.get("areas", {}).get(area_id, {})
    var exit := _find_exit(area, exit_id)
    if exit.is_empty():
        message = "No exit here."
        return
    if bool(exit.get("frontier", false)):
        if _run_worldgen([
            "expand", "--state", ProjectSettings.globalize_path(STATE_PATH),
            "--area", area_id, "--exit", exit_id
        ]):
            _load_state()
            _place_on_entry()
        else:
            message = "That frontier is still gated."
    else:
        if _run_worldgen([
            "travel", "--state", ProjectSettings.globalize_path(STATE_PATH),
            "--area", area_id, "--exit", exit_id
        ]):
            _load_state()
            _place_on_entry()

func _find_exit(area: Dictionary, id: String) -> Dictionary:
    for item in area.get("exits", []):
        if String(item.get("id", "")) == id:
            return item
    return {}

func _has_exit(area: Dictionary, id: String) -> bool:
    return not _find_exit(area, id).is_empty()

func _load_state() -> void:
    if not FileAccess.file_exists(STATE_PATH):
        return
    var f := FileAccess.open(STATE_PATH, FileAccess.READ)
    var parsed = JSON.parse_string(f.get_as_text())
    if typeof(parsed) == TYPE_DICTIONARY:
        state = parsed
        area_id = String(state.get("current_area", "oaks_lab"))
        message = "Loaded persistent world: %s" % area_id

func _place_on_entry() -> void:
    player = Vector2(175, 355) if area_id != "oaks_lab" else Vector2(480, 360)
    message = "Entered %s." % String(state["areas"][area_id]["name"])

func _find_worldgen() -> String:
    var exe := "worldgen.exe" if OS.get_name() == "Windows" else "worldgen"
    var candidates := [
        ProjectSettings.globalize_path("res://bin/" + exe),
        ProjectSettings.globalize_path("res://../../target/release/" + exe),
        OS.get_executable_path().get_base_dir().path_join(exe)
    ]
    for p in candidates:
        if FileAccess.file_exists(p):
            return p
    return candidates[0]

func _run_worldgen(args: Array[String]) -> bool:
    if not FileAccess.file_exists(worldgen_path):
        message = "worldgen binary missing. Run scripts/build_vertical first."
        return false
    var output: Array = []
    var code := OS.execute(worldgen_path, args, output, true)
    if code != 0:
        message = "worldgen error: %s" % "\n".join(output)
        return false
    return true

func _reset_save() -> void:
    if FileAccess.file_exists(STATE_PATH):
        DirAccess.remove_absolute(ProjectSettings.globalize_path(STATE_PATH))

func _fallback_bootstrap() -> void:
    state = {
        "version": 1,
        "seed": 42,
        "badges": 0,
        "player_level_hint": 5,
        "current_area": "oaks_lab",
        "starter": null,
        "rival_defeated": false,
        "areas": {},
        "promises": {},
        "history": ["FALLBACK_BOOTSTRAP"]
    }
    message = "worldgen binary missing; run build script for full vertical."
