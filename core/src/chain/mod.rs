//! Typed boundary to the authoritative Veracity contract and Ethereum JSON-RPC.

mod client;
mod types;

pub use client::{ChainClient, commitment_hash};
pub use types::*;
