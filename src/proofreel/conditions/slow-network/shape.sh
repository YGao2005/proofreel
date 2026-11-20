#!/bin/sh
set -eu
DOWN=proofreel-down UP=proofreel-up
PIPE_DOWN=47001 PIPE_UP=47002 ANCHOR=com.apple/proofreel-slow-network

fail() { echo "slow-network: $*" >&2; exit 2; }

number() {
  case $2 in ''|*[!0-9.]*|*.*.*) fail "$1=$3: $4" ;; esac
}

half() { awk -v n="$1" 'BEGIN { printf "%.10g", n / 2 }'; }

parse() {
  number latency "${latency%ms}" "$latency" "write milliseconds, such as 200ms."
  number jitter "${jitter%ms}" "$jitter" "write milliseconds, such as 50ms."
  number loss "${loss%\%}" "$loss" "write a percent, such as 5%."
  case $rate in
    *kbit) n=${rate%kbit} f=1 ;;
    *mbit) n=${rate%mbit} f=1000 ;;
    0) n=0 f=1 ;;
    *) n=x f=1 ;;
  esac
  number rate "$n" "$rate" "write kbit or mbit, such as 1mbit, or 0 for no cap."
  DELAY=$(half "${latency%ms}") JITTER=$(half "${jitter%ms}") LOSS=${loss%\%}
  KBIT=$(awk -v n="$n" -v f="$f" 'BEGIN { printf "%.10g", n * f }')
}

device() {
  dev=$(ip route show default | awk '{ for (i = 1; i < NF; i++) if ($i == "dev") { print $(i + 1); exit } }')
  [ -n "$dev" ] || fail "the guest has no default route, so no interface to shape."
  echo "$dev"
}

Linux_apply() {
  dev=$(device)
  netem="delay ${DELAY}ms"
  [ "$JITTER" = 0 ] || netem="$netem ${JITTER}ms"
  [ "$LOSS" = 0 ] || netem="$netem loss ${LOSS}%"
  [ "$KBIT" = 0 ] || netem="$netem rate ${KBIT}kbit"
  for link in $DOWN $UP; do
    sudo ip link add "$link" type ifb
    sudo ip link set "$link" up
    sudo tc qdisc add dev "$link" root netem $netem
  done
  sudo tc qdisc add dev "$dev" clsact
  sudo tc filter add dev "$dev" ingress prio 1 protocol ip flower ip_proto tcp dst_port 22 action pass
  sudo tc filter add dev "$dev" ingress prio 2 matchall action mirred egress redirect dev $DOWN
  sudo tc filter add dev "$dev" egress prio 1 protocol ip flower ip_proto tcp src_port 22 action pass
  sudo tc filter add dev "$dev" egress prio 2 matchall action mirred egress redirect dev $UP
}

Linux_check() {
  dev=$(device)
  for link in $DOWN $UP; do
    sudo tc qdisc show dev "$link" 2>/dev/null | grep -q netem || { echo "$link has no netem."; exit 1; }
  done
  sudo tc filter show dev "$dev" ingress | grep -q "device $DOWN" || { echo "$dev does not send its input to $DOWN."; exit 1; }
  sudo tc filter show dev "$dev" egress | grep -q "device $UP" || { echo "$dev does not send its output to $UP."; exit 1; }
  shaping=$(sudo tc qdisc show dev $DOWN | sed 's/.* limit [0-9]* //; s/ seed .*//' | tr -s ' ')
  echo "Shaped on $dev, each way: $shaping. SSH is not shaped."
}

Linux_remove() {
  dev=$(device)
  sudo tc qdisc del dev "$dev" clsact 2>/dev/null || true
  for link in $DOWN $UP; do sudo ip link del "$link" 2>/dev/null || true; done
  left=$(sudo tc qdisc show dev "$dev" | grep clsact || true)
  for link in $DOWN $UP; do
    if ip link show "$link" >/dev/null 2>&1; then left="$left $link"; fi
  done
  [ -z "$left" ] || { echo "Still shaped: $left"; exit 1; }
  echo "Not shaped: $dev has no clsact, and $DOWN and $UP are gone."
}

Darwin_apply() {
  ms=$(awk -v n="$DELAY" 'BEGIN { printf "%d", n + 0.5 }')
  plr=$(awk -v n="$LOSS" 'BEGIN { printf "%.6g", n / 100 }')
  bw=""
  [ "$KBIT" = 0 ] || bw="bw ${KBIT}Kbit/s"
  for pipe in $PIPE_DOWN $PIPE_UP; do sudo dnctl pipe $pipe config delay "$ms" plr "$plr" $bw; done
  printf '%s\n' "no dummynet quick on lo0 all" \
    "no dummynet quick proto tcp from any to any port 22" "no dummynet quick proto tcp from any port 22 to any" \
    "dummynet in quick all pipe $PIPE_DOWN" "dummynet out quick all pipe $PIPE_UP" | sudo pfctl -q -a $ANCHOR -f -
  sudo pfctl -E 2>&1 | sed -n 's/^Token : //p' > token
}

Darwin_check() {
  sudo pfctl -s info 2>/dev/null | grep -q "Status: Enabled" || { echo "pf is off."; exit 1; }
  rules=$(sudo pfctl -a $ANCHOR -s dummynet 2>/dev/null)
  echo "$rules" | grep -q "pipe $PIPE_DOWN" || { echo "pf has no proofreel dummynet rules."; exit 1; }
  # WHY: dnctl list stops after a pipe that holds packets, so the other pipe can be missing from the list.
  pipe=$(sudo dnctl list 2>/dev/null | grep -E "^0*($PIPE_DOWN|$PIPE_UP):" | head -1)
  [ -n "$pipe" ] || { echo "dummynet has no proofreel pipe."; exit 1; }
  shaping=$(echo "$pipe" | sed 's/^[0-9]*: *//; s/ [0-9]* sl\./ /; s/ [0-9]* queues.*//' | tr -s ' ')
  [ "${jitter:-0ms}" = 0ms ] || shaping="$shaping, no jitter (dummynet has none)"
  echo "Shaped each way: $shaping. SSH is not shaped."
}

Darwin_remove() {
  sudo pfctl -q -a $ANCHOR -F all 2>/dev/null || true
  sudo dnctl pipe delete $PIPE_DOWN $PIPE_UP 2>/dev/null || true
  [ ! -s token ] || sudo pfctl -X "$(cat token)" >/dev/null 2>&1 || true
  rm -f token
  left=$(sudo pfctl -a $ANCHOR -s dummynet 2>/dev/null; sudo dnctl list 2>/dev/null | grep -E "^0*($PIPE_DOWN|$PIPE_UP):" || true)
  [ -z "$left" ] || { echo "Still shaped: $left"; exit 1; }
  echo "Not shaped: the pf anchor and the dummynet pipes are gone."
}

os=$(uname)
case $1 in
  apply) parse; sh remove.sh >/dev/null; "${os}_apply" ;;
  check|remove) "${os}_$1" ;;
  *) fail "no step $1." ;;
esac
