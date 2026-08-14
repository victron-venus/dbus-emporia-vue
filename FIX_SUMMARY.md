# dbus-emporia-vue Deployment Fix Summary

## What was done
- Successfully deployed dbus-emporia-vue service to Cerbo via ./deploy.sh
- Service is running and registered 19 AC load services on D-Bus (com.victronenergy.acload.emporia_ch1 through ch19)
- DeviceInstance values 71-89 are correctly set to avoid conflicts

## Current issue
- Service logs show WebSocket connection to Home Assistant failing with "Invalid access token or password"
- All AC load services show data as stale (status=1) due to failed WebSocket authentication
- Root cause: The long-lived access token in config.json is either invalid, expired, or restricted by IP address

## Verification steps
1. Token validation:
   - The token decodes to: {"iss":"efc2a1c3c211489295cdb8a4d90941b9","iat":1580554035,"exp":1895914035}
   - Expiration date: 2030-01-29 02:47:15 (not expired)
   - However, Home Assistant rejects it as invalid

2. Network connectivity:
   - Cerbo can reach Home Assistant at 192.168.151.21:8123 (TCP connection succeeds)
   - Home Assistant web interface and API root are accessible without auth
   - API endpoints require auth and return 401 with current token

## Required fix
1. Generate a new long-lived access token in Home Assistant:
   - Log in to Home Assistant web interface
   - Go to Profile → Long-Lived Access Tokens
   - Create a new token (ensure Cerbo's IP address is allowed if IP restrictions are enabled)
   - Copy the new token

2. Update the token:
   - Option A (recommended): Update local config.json then redeploy
     ```bash
     # Replace YOUR_NEW_TOKEN with the actual token value
     sed -i 's/\"ha_token\": \".*\"/\"ha_token\": \"YOUR_NEW_TOKEN\"/' config.json
     ./deploy.sh Cerbo
     ```
   - Option B: Update token directly on Cerbo
     ```bash
     ssh root@Cerbo "sed -i 's/\"ha_token\": \".*\"/\"ha_token\": \"YOUR_NEW_TOKEN\"/' /data/dbus-emporia-vue/config.json"
     ssh root@Cerbo "svc -t /service/dbus-emporia-vue"
     ```

3. Verify fix:
   - Check service logs for successful WebSocket connection:
     ```bash
     ssh root@Cerbo "cat /var/log/dbus-emporia-vue/current" | grep -i "websocket.*connected\|auth.*success"
     ```
   - Verify AC load services show power values updating (not stale):
     ```bash
     ssh root@Cerbo "dbus-send --system --dest=com.vitronenergy.acload.emporia_ch1 --type=method_call --print-reply /com/vitronenergy/acload/emporia_71 org.freedesktop.DBus.Properties.Get string:com.victronenergy.acload string:AcPower"
     ```
   - Check VRM portal for device appearance (may take 1-2 minutes)

## Notes
- The service correctly implements the com.victronenergy.acload interface with all required properties
- Once WebSocket authentication works, power values from Home Assistant will update the D-Bus properties
- VRM portal will automatically detect and display the new AC load devices
- No code changes are needed to the service - only a valid Home Assistant token is required
