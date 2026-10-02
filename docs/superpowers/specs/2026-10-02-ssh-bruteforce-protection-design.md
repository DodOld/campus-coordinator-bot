# SSH brute-force protection design

## Goal

Reduce password-guessing attacks on the production server without removing the
existing password-based SSH access or root login.

## Configuration

- Install and enable `fail2ban`.
- Enable a dedicated `sshd` jail using the system SSH journal.
- A source IP is banned after three failed SSH authentication attempts within
  ten minutes.
- The ban lasts twenty-four hours.
- `banaction` uses UFW so the ban applies at the host firewall.
- No IP allow-list is configured: the operator explicitly chose not to exempt
  their changing public IP address.
- `PermitRootLogin` and `PasswordAuthentication` are not changed by this task.

## Safety and verification

- Existing SSH sessions remain connected while the service is installed and
  started.
- Before ending the operation, verify that `fail2ban` is running, the `sshd`
  jail is enabled, and `fail2ban-client status sshd` reports the configured
  jail.
- Do not simulate failed logins from the operator's address, because the chosen
  threshold is intentionally strict.

## Out of scope

- SSH key-only migration, disabling root login, cloud-firewall restrictions,
  password rotation, and compromise investigation require separate approval.
