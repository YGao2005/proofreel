#!/bin/sh
set -eu
user=$1
export DEBIAN_FRONTEND=noninteractive

systemctl disable --now apt-daily.timer apt-daily-upgrade.timer apt-listchanges.timer man-db.timer
apt-get purge -y unattended-upgrades
apt-get update
apt-get install -y --no-install-recommends xserver-xorg-core xserver-xorg-video-fbdev xserver-xorg-input-libinput \
  x11-xserver-utils xfce4-session xfwm4 xfce4-panel xfdesktop4 xfce4-settings xfce4-terminal xfconf \
  lightdm lightdm-gtk-greeter dbus-user-session dbus-x11 at-spi2-core chromium fonts-dejavu-core fonts-liberation
apt-get clean

# WHY: the EFI stub takes the largest firmware mode, which is the `vm up --display` size.
sed -i 's/^GRUB_CMDLINE_LINUX=""/GRUB_CMDLINE_LINUX="video=efifb:auto"/' /etc/default/grub
update-grub

mkdir -p /etc/X11/xorg.conf.d /etc/lightdm/lightdm.conf.d /etc/chromium/policies/managed
cat > /etc/X11/xorg.conf.d/10-proofreel.conf <<'EOF'
Section "ServerFlags"
  Option "BlankTime" "0"
  Option "StandbyTime" "0"
  Option "SuspendTime" "0"
  Option "OffTime" "0"
EndSection
EOF
# WHY: logind marks a seat graphical only for a DRM device, and this kernel has only efifb.
cat > /etc/lightdm/lightdm.conf.d/50-proofreel.conf <<EOF
[LightDM]
logind-check-graphical=false
[Seat:*]
autologin-user=$user
autologin-user-timeout=0
autologin-session=xfce
user-session=xfce
EOF
cat > /etc/chromium.d/proofreel <<'EOF'
export CHROMIUM_FLAGS="$CHROMIUM_FLAGS --no-first-run --no-default-browser-check --password-store=basic --start-maximized"
EOF
cat > /etc/chromium/policies/managed/proofreel.json <<'EOF'
{"DefaultBrowserSettingEnabled": false, "PromotionalTabsEnabled": false, "PasswordManagerEnabled": false,
 "AutofillAddressEnabled": false, "AutofillCreditCardEnabled": false, "TranslateEnabled": false,
 "BrowserSignin": 0, "SyncDisabled": true, "MetricsReportingEnabled": false, "PrivacySandboxPromptEnabled": false,
 "ComponentUpdatesEnabled": false, "BackgroundModeEnabled": false, "RestoreOnStartup": 5,
 "HideWebStoreIcon": true, "ShowHomeButton": false}
EOF
echo DISPLAY=:0 >> /etc/environment
cat > /usr/local/bin/browse <<'EOF'
#!/bin/sh
prefs="$HOME/.config/chromium/Default/Preferences"
pgrep -x chromium >/dev/null || { [ -f "$prefs" ] && sed -i 's/"exit_type":"[A-Za-z]*"/"exit_type":"Normal"/' "$prefs"; }
DISPLAY=:0 setsid -f chromium "$@" >/dev/null 2>&1 </dev/null
EOF
chmod 755 /usr/local/bin/browse

home=$(getent passwd "$user" | cut -d: -f6)
panel=$home/.config/xfce4/xfconf/xfce-perchannel-xml
mkdir -p "$panel"
cp /etc/xdg/xfce4/panel/default.xml "$panel/xfce4-panel.xml"
chown -R "$user:$user" "$home/.config"

touch /etc/cloud/cloud-init.disabled
systemctl set-default graphical.target
