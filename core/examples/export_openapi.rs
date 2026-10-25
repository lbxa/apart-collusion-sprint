//! Export the API contract without starting HTTP or an Anvil subprocess.

fn main() -> Result<(), Box<dyn std::error::Error>> {
    println!(
        "{}",
        serde_json::to_string_pretty(&veracity_game_service::api::openapi())?
    );
    Ok(())
}
