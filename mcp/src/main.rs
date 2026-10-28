#[tokio::main]
async fn main() -> anyhow::Result<()> {
    use std::io::IsTerminal;
    use tracing_subscriber::{fmt, EnvFilter};

    // Colour only on a terminal: under systemd stdout is a log file/journal,
    // and ANSI escapes there made gateway.log unreadable without `less -R`.
    let ansi = std::io::stdout().is_terminal() && std::env::var_os("NO_COLOR").is_none();
    fmt()
        .with_env_filter(EnvFilter::try_from_default_env().unwrap_or_else(|_| "info".into()))
        .with_ansi(ansi)
        .init();

    let settings = advandeb_mcp::config::Settings::load()?;
    advandeb_mcp::serve(settings).await
}
