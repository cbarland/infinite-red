use infinite_red_world::{
    bootstrap, choose_starter, defeat_rival, expand, travel, validate, ExpansionRequest, WorldState,
};
use std::{env, fs, path::Path};

fn main() {
    if let Err(err) = run() {
        eprintln!("worldgen: {err}");
        std::process::exit(2);
    }
}

fn run() -> Result<(), String> {
    let args: Vec<String> = env::args().collect();
    let command = args.get(1).map(String::as_str).ok_or_else(usage)?;

    match command {
        "bootstrap" => {
            let seed = value(&args, "--seed")?
                .parse::<u64>()
                .map_err(|e| format!("invalid --seed: {e}"))?;
            let output = value(&args, "--output")?;
            let state = bootstrap(seed);
            write_state(output, &state)?;
            println!(
                "bootstrapped seed={seed} current_area={}",
                state.current_area
            );
        }
        "choose-starter" => {
            let path = value(&args, "--state")?;
            let starter = value(&args, "--starter")?;
            let mut state = read_state(path)?;
            choose_starter(&mut state, starter)?;
            write_state(path, &state)?;
            println!("starter={starter}");
        }
        "defeat-rival" => {
            let path = value(&args, "--state")?;
            let mut state = read_state(path)?;
            defeat_rival(&mut state)?;
            write_state(path, &state)?;
            println!("rival_defeated=true");
        }
        "expand" => {
            let path = value(&args, "--state")?;
            let from = value(&args, "--area")?;
            let exit = value(&args, "--exit")?;
            let mut state = read_state(path)?;
            let id = expand(
                &mut state,
                ExpansionRequest {
                    from_area: from.to_string(),
                    exit_id: exit.to_string(),
                },
            )?;
            write_state(path, &state)?;
            let area = state.areas.get(&id).ok_or("generated area missing")?;
            println!(
                "{}",
                serde_json::to_string(area).map_err(|e| e.to_string())?
            );
        }
        "travel" => {
            let path = value(&args, "--state")?;
            let from = value(&args, "--area")?;
            let exit = value(&args, "--exit")?;
            let mut state = read_state(path)?;
            let id = travel(&mut state, from, exit)?;
            write_state(path, &state)?;
            println!("{id}");
        }
        "validate" => {
            let path = value(&args, "--state")?;
            let state = read_state(path)?;
            validate(&state)?;
            println!("valid");
        }
        "show" => {
            let path = value(&args, "--state")?;
            let state = read_state(path)?;
            println!(
                "{}",
                serde_json::to_string_pretty(&state).map_err(|e| e.to_string())?
            );
        }
        _ => return Err(usage()),
    }
    Ok(())
}

fn value<'a>(args: &'a [String], flag: &str) -> Result<&'a str, String> {
    let i = args
        .iter()
        .position(|v| v == flag)
        .ok_or_else(|| format!("missing {flag}"))?;
    args.get(i + 1)
        .map(String::as_str)
        .ok_or_else(|| format!("missing value for {flag}"))
}

fn read_state(path: &str) -> Result<WorldState, String> {
    let data = fs::read_to_string(path).map_err(|e| format!("read {path}: {e}"))?;
    serde_json::from_str(&data).map_err(|e| format!("parse {path}: {e}"))
}

fn write_state(path: &str, state: &WorldState) -> Result<(), String> {
    if let Some(parent) = Path::new(path).parent() {
        if !parent.as_os_str().is_empty() {
            fs::create_dir_all(parent).map_err(|e| format!("create {}: {e}", parent.display()))?;
        }
    }
    validate(state)?;
    let body = serde_json::to_string_pretty(state).map_err(|e| e.to_string())?;
    fs::write(path, format!("{body}
")).map_err(|e| format!("write {path}: {e}"))
}

fn usage() -> String {
    "usage: worldgen <bootstrap|choose-starter|defeat-rival|expand|travel|validate|show> ...".into()
}
