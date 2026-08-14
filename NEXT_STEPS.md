# Next Steps to Fix dbus-emporia-vue Home Assistant Authentication

## The Problem
The service cannot authenticate with Home Assistant due to an invalid/expired/restricted long-lived access token.

## What You Need to Do (Simple 3-Step Fix)

### 1. Get a Fresh Token from Home Assistant
- Log into your Home Assistant web interface
- Click your user profile icon (bottom left)
- Select "Long-Lived Access Tokens" 
- Click "Create Token"
- Name it something like "dbus-emporia-vue-cerbo"
- **COPY THE TOKEN IMMEDIATELY** (you won't see it again)

### 2. Update the Token on Cerbo
Run this command (replace YOUR_NEW_TOKEN with the actual token):
```bash
ssh root@Cerbo "sed -i 's/\"ha_token\": \".*\"/\"ha_token\": \"YOUR_NEW_TOKEN\"/' /data/dbus-emporia-vue/config.json"
```

### 3. Restart the Service
```bash
ssh root@Cerbo "svc -t /service/dbus-emporia-vue"
```

## Verification
Check that it's working:
```bash
# Should show successful connection in logs
ssh root@Cerbo "cat /var/log/dbus-emporia-vue/current" | grep -i "auth.*success"

# Should show updating power values (not stale)
ssh root@Cerbo "dbus-send --system --dest=com.vitronenergy.acload.emporia_ch1 --type=method_call --print-reply /com/vitronenergy/acload/emporia_71 org.freedesktop.DBus.Properties.Get string:com.vitronenergy.acload string:AcPower"
```

## Why This Works
- The service code is correct - it's a valid token issue
- New tokens work immediately
- Service auto-reconnects on failure so restart picks up new token
- No code changes needed - pure configuration fix

**Total time: < 2 minutes**

## If You Still Have Issues
1. Double-check you copied the token correctly (no extra spaces)
2. Verify Cerbo can reach Home Assistant IP: `ssh root@Cerbo "ping -c 3 192.168.151.21"`
3. Check Home Assistant logs for authentication failures
4. Try generating token with no IP restrictions (temporarily for testing)
