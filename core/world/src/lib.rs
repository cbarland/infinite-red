use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct WorldState {
    pub version: u32,
    pub seed: u64,
    pub badges: u8,
    pub player_level_hint: u8,
    pub current_area: String,
    pub starter: Option<String>,
    pub rival_defeated: bool,
    pub areas: BTreeMap<String, Area>,
    pub promises: BTreeMap<String, Promise>,
    pub history: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Area {
    pub id: String,
    pub name: String,
    pub kind: AreaKind,
    pub challenge: f32,
    pub came_from: Option<String>,
    pub exits: Vec<Exit>,
    pub npcs: Vec<Npc>,
    pub notes: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum AreaKind {
    Interior,
    Settlement,
    Route,
    Dungeon,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Exit {
    pub id: String,
    pub label: String,
    pub to_area: Option<String>,
    pub gate: Gate,
    pub frontier: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(tag = "type", content = "value", rename_all = "snake_case")]
pub enum Gate {
    Open,
    StarterChosen,
    RivalDefeated,
    Badge(u8),
    Hm(String),
    KeyItem(String),
    Story(String),
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Npc {
    pub id: String,
    pub name: String,
    pub role: String,
    pub interaction: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Promise {
    pub id: String,
    pub setup_area: String,
    pub setup: String,
    pub payoff_hint: String,
    pub resolved: bool,
}

#[derive(Debug, Clone)]
pub struct ExpansionRequest {
    pub from_area: String,
    pub exit_id: String,
}

pub fn bootstrap(seed: u64) -> WorldState {
    let mut areas = BTreeMap::new();
    areas.insert(
        "oaks_lab".into(),
        Area {
            id: "oaks_lab".into(),
            name: "Oak's Lab".into(),
            kind: AreaKind::Interior,
            challenge: 1.0,
            came_from: None,
            exits: vec![Exit {
                id: "south_door".into(),
                label: "South Door".into(),
                to_area: None,
                gate: Gate::RivalDefeated,
                frontier: true,
            }],
            npcs: vec![
                Npc {
                    id: "oak".into(),
                    name: "Professor Oak".into(),
                    role: "mentor".into(),
                    interaction: "choose_starter".into(),
                },
                Npc {
                    id: "rival".into(),
                    name: "Rival".into(),
                    role: "rival".into(),
                    interaction: "starter_battle".into(),
                },
            ],
            notes: vec!["Fixed authored prologue anchor.".into()],
        },
    );

    WorldState {
        version: 1,
        seed,
        badges: 0,
        player_level_hint: 5,
        current_area: "oaks_lab".into(),
        starter: None,
        rival_defeated: false,
        areas,
        promises: BTreeMap::new(),
        history: vec!["BOOTSTRAP:oaks_lab".into()],
    }
}

pub fn choose_starter(state: &mut WorldState, starter: &str) -> Result<(), String> {
    let normalized = starter.to_ascii_lowercase();
    let allowed = ["bulbasaur", "charmander", "squirtle"];
    if !allowed.contains(&normalized.as_str()) {
        return Err("starter must be bulbasaur, charmander, or squirtle".into());
    }
    state.starter = Some(normalized.clone());
    state.history.push(format!("STARTER:{normalized}"));
    Ok(())
}

pub fn defeat_rival(state: &mut WorldState) -> Result<(), String> {
    if state.starter.is_none() {
        return Err("choose a starter first".into());
    }
    state.rival_defeated = true;
    state.player_level_hint = state.player_level_hint.max(6);
    state.history.push("RIVAL_DEFEATED:oaks_lab".into());
    Ok(())
}

pub fn gate_open(state: &WorldState, gate: &Gate) -> bool {
    match gate {
        Gate::Open => true,
        Gate::StarterChosen => state.starter.is_some(),
        Gate::RivalDefeated => state.rival_defeated,
        Gate::Badge(n) => state.badges >= *n,
        Gate::Hm(hm) => state
            .history
            .iter()
            .any(|h| h == &format!("HM_ACQUIRED:{hm}")),
        Gate::KeyItem(item) => state
            .history
            .iter()
            .any(|h| h == &format!("KEY_ITEM_ACQUIRED:{item}")),
        Gate::Story(flag) => state
            .history
            .iter()
            .any(|h| h == &format!("STORY_RESOLVED:{flag}")),
    }
}

pub fn expand(state: &mut WorldState, req: ExpansionRequest) -> Result<String, String> {
    let from = state
        .areas
        .get(&req.from_area)
        .cloned()
        .ok_or_else(|| format!("unknown area {}", req.from_area))?;

    let exit = from
        .exits
        .iter()
        .find(|e| e.id == req.exit_id)
        .cloned()
        .ok_or_else(|| format!("unknown exit {}", req.exit_id))?;

    if !exit.frontier {
        if let Some(target) = exit.to_area {
            state.current_area = target.clone();
            return Ok(target);
        }
        return Err("exit is neither frontier nor connected".into());
    }

    if !gate_open(state, &exit.gate) {
        return Err(format!("gate is closed: {:?}", exit.gate));
    }

    let area_index = state.areas.len() as u64;
    let roll = mix64(
        state.seed
            ^ stable_hash(&req.from_area)
            ^ stable_hash(&req.exit_id)
            ^ area_index.wrapping_mul(0x9E37_79B9_7F4A_7C15),
    );

    let new_id = format!("area_{:04}", state.areas.len());
    let (name, kind) = if from.id == "oaks_lab" {
        ("Mountain Village".to_string(), AreaKind::Settlement)
    } else {
        let names = [
            "Cedar Pass",
            "Mosswater Crossing",
            "Amber Hollow",
            "Juniper Vale",
            "Granite Trail",
            "Willowmere",
        ];
        (
            names[(roll as usize) % names.len()].to_string(),
            if roll & 1 == 0 {
                AreaKind::Route
            } else {
                AreaKind::Settlement
            },
        )
    };

    let increase = if from.id == "oaks_lab" {
        0.17
    } else {
        0.08 + ((roll % 9) as f32 / 100.0)
    };
    let challenge = round2((from.challenge + increase).max(1.0));

    let promise_id = if from.id == "oaks_lab" {
        Some("STORY:ROAD_CLEARED".to_string())
    } else if roll % 3 == 0 {
        Some(format!("STORY:BLOCKAGE_{:04}", state.areas.len()))
    } else {
        None
    };

    let mut exits = vec![
        Exit {
            id: "back".into(),
            label: format!("Back to {}", from.name),
            to_area: Some(from.id.clone()),
            gate: Gate::Open,
            frontier: false,
        },
        Exit {
            id: "east_frontier".into(),
            label: "East Frontier".into(),
            to_area: None,
            gate: Gate::Open,
            frontier: true,
        },
    ];

    if let Some(pid) = &promise_id {
        exits.push(Exit {
            id: "north_blocked".into(),
            label: "Damaged North Road".into(),
            to_area: None,
            gate: Gate::Story(pid.clone()),
            frontier: true,
        });
    }

    let area = Area {
        id: new_id.clone(),
        name: name.clone(),
        kind,
        challenge,
        came_from: Some(from.id.clone()),
        exits,
        npcs: vec![
            Npc {
                id: format!("guide_{}", state.areas.len()),
                name: "Trail Guide".into(),
                role: "guide".into(),
                interaction: "world_hint".into(),
            },
            Npc {
                id: format!("trainer_{}", state.areas.len()),
                name: "Young Trainer".into(),
                role: "trainer".into(),
                interaction: "optional_battle".into(),
            },
        ],
        notes: vec![
            format!("Generated from {}", from.name),
            format!("badge_count={}", state.badges),
            format!("player_level_hint={}", state.player_level_hint),
            "Challenge derives primarily from predecessor area.".into(),
        ],
    };

    if let Some(existing_from) = state.areas.get_mut(&req.from_area) {
        if let Some(existing_exit) = existing_from.exits.iter_mut().find(|e| e.id == req.exit_id) {
            existing_exit.to_area = Some(new_id.clone());
            existing_exit.frontier = false;
        }
    }

    if let Some(pid) = promise_id {
        state.promises.insert(
            pid.clone(),
            Promise {
                id: pid.clone(),
                setup_area: new_id.clone(),
                setup: "A damaged road visibly continues north but cannot yet be crossed.".into(),
                payoff_hint: "Director may resolve through HM, key item, badge, NPC, battle, or story event.".into(),
                resolved: false,
            },
        );
    }

    state.areas.insert(new_id.clone(), area);
    state.current_area = new_id.clone();
    state.history.push(format!(
        "EXPAND:{}:{}->{}",
        req.from_area, req.exit_id, new_id
    ));

    validate(state)?;
    Ok(new_id)
}

pub fn travel(state: &mut WorldState, from_area: &str, exit_id: &str) -> Result<String, String> {
    let area = state
        .areas
        .get(from_area)
        .ok_or_else(|| format!("unknown area {from_area}"))?;
    let exit = area
        .exits
        .iter()
        .find(|e| e.id == exit_id)
        .ok_or_else(|| format!("unknown exit {exit_id}"))?;
    if !gate_open(state, &exit.gate) {
        return Err(format!("gate is closed: {:?}", exit.gate));
    }
    let target = exit
        .to_area
        .clone()
        .ok_or_else(|| "exit is an ungenerated frontier".to_string())?;
    state.current_area = target.clone();
    state
        .history
        .push(format!("TRAVEL:{from_area}:{exit_id}->{target}"));
    Ok(target)
}

pub fn validate(state: &WorldState) -> Result<(), String> {
    if state.version != 1 {
        return Err(format!("unsupported world version {}", state.version));
    }
    if !state.areas.contains_key(&state.current_area) {
        return Err("current_area does not exist".into());
    }

    let mut ids = BTreeSet::new();
    for (id, area) in &state.areas {
        if id != &area.id {
            return Err(format!("area map key {id} != area.id {}", area.id));
        }
        if !ids.insert(id) {
            return Err(format!("duplicate area id {id}"));
        }
        if area.challenge < 1.0 {
            return Err(format!("area {id} has invalid challenge"));
        }
        for exit in &area.exits {
            if exit.frontier && exit.to_area.is_some() {
                return Err(format!("frontier {}:{} already has target", id, exit.id));
            }
            if !exit.frontier {
                if let Some(target) = &exit.to_area {
                    if !state.areas.contains_key(target) {
                        return Err(format!("{}:{} points to missing {target}", id, exit.id));
                    }
                }
            }
        }
    }

    for (pid, promise) in &state.promises {
        if pid != &promise.id {
            return Err(format!("promise key {pid} != id {}", promise.id));
        }
        if !state.areas.contains_key(&promise.setup_area) {
            return Err(format!("promise {pid} setup area missing"));
        }
    }

    Ok(())
}

fn stable_hash(s: &str) -> u64 {
    let mut h = 0xcbf29ce484222325u64;
    for b in s.as_bytes() {
        h ^= *b as u64;
        h = h.wrapping_mul(0x100000001b3);
    }
    h
}

fn mix64(mut x: u64) -> u64 {
    x ^= x >> 30;
    x = x.wrapping_mul(0xbf58476d1ce4e5b9);
    x ^= x >> 27;
    x = x.wrapping_mul(0x94d049bb133111eb);
    x ^ (x >> 31)
}

fn round2(v: f32) -> f32 {
    (v * 100.0).round() / 100.0
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn first_expansion_is_deterministic_and_progressive() {
        let mut w = bootstrap(42);
        choose_starter(&mut w, "charmander").unwrap();
        defeat_rival(&mut w).unwrap();
        let id = expand(
            &mut w,
            ExpansionRequest {
                from_area: "oaks_lab".into(),
                exit_id: "south_door".into(),
            },
        )
        .unwrap();

        let a = w.areas.get(&id).unwrap();
        assert_eq!(a.name, "Mountain Village");
        assert_eq!(a.challenge, 1.17);
        assert_eq!(a.came_from.as_deref(), Some("oaks_lab"));
        assert!(w.promises.contains_key("STORY:ROAD_CLEARED"));
        assert!(a.exits.iter().any(|e| e.id == "east_frontier" && e.frontier));
        validate(&w).unwrap();
    }

    #[test]
    fn lab_exit_is_gated_by_rival_milestone() {
        let mut w = bootstrap(7);
        let err = expand(
            &mut w,
            ExpansionRequest {
                from_area: "oaks_lab".into(),
                exit_id: "south_door".into(),
            },
        )
        .unwrap_err();
        assert!(err.contains("gate is closed"));
    }
}
