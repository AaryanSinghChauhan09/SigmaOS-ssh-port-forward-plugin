#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SshTunnel {
    pub name: String,
    pub remote_host: String,
    pub local_port: u16,
    pub remote_port: u16,
    pub is_active: bool,
}

#[derive(Debug, Default)]
pub struct PortForwardManager {
    tunnels: Vec<SshTunnel>,
}

impl PortForwardManager {
    pub fn new() -> Self { Self { tunnels: Vec::new() } }
    pub fn create_tunnel(&mut self, name: &str, r_host: &str, l_port: u16, r_port: u16) {
        self.tunnels.push(SshTunnel {
            name: name.into(),
            remote_host: r_host.into(),
            local_port: l_port,
            remote_port: r_port,
            is_active: false,
        });
    }
    pub fn start_tunnel(&mut self, name: &str) -> bool {
        if let Some(t) = self.tunnels.iter_mut().find(|t| t.name == name) {
            t.is_active = true;
            true
        } else {
            false
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn test_port_forward_manager_aaa() {
        // Arrange
        let mut mgr = PortForwardManager::new();
        mgr.create_tunnel("dev-db", "db.internal", 5432, 5432);
        // Act
        let started = mgr.start_tunnel("dev-db");
        // Assert
        assert!(started);
    }
}
