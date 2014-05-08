#!/bin/bash 
#
# This file is part of pyracast.
#
# pyracast is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# pyracast is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# ---
#
# Most of this file is taken from or at least heavily inspired by the
# piracast project, licensed under GPLv3 or later, found at
# https://github.com/codemonkeyricky/piracast

test "$1" = "-d" && set -x

LF="./var/dhcpd.leases"

p2p_enable() {
	sudo iwpriv wlan0 p2p_set enable=1
	sudo iwpriv wlan0 p2p_set intent=15
	sudo iwpriv wlan0 p2p_set op_ch=11
	sleep 0.05
	sudo iwpriv wlan0 p2p_set ssid=DIRECT-py
	sudo iwpriv wlan0 p2p_set setDN=pyracast
}

p2p_disable() {
	sudo iwpriv wlan0 p2p_set enable=0
}

p2p_peer_scan() {
	COUNT=0

	while sleep 1; do
		sudo iwlist wlan0 scan | grep -q "No scan results" || return 0

		test $COUNT -gt 3 && return 1

		COUNT=$(($COUNT+1))
	done
}

p2p_get_status() {
	sudo iwpriv wlan0 p2p_get status | grep ^Status= | cut -d= -f 2
}

dhcpd_start() {
	sudo sh -c '> $LF'
	sudo /usr/sbin/dhcpd -pf ./var/dhcpd.pid -cf ./dhcpd.conf -lf $LF wlan0
}

dhcpd_stop() {
	test -f ./var/dhcpd.pid || return
	test -n "$(< ./var/dhcpd.pid)" || return
	sudo kill "$(< ./var/dhcpd.pid)"
}

hostapd_start() {
	sudo ./hostapd -B -P ./var/hostapd.pid hostapd-p2p.conf
}

hostapd_stop() {
	test -f ./var/hostapd.pid || return
	test -n "$(< ./var/hostapd.pid)" || return
	sudo kill "$(< ./var/hostapd.pid)"
}

cleanup() {
	p2p_disable
	hostapd_stop
	dhcpd_stop
}

> ./var/dhcpd.pid
> ./var/hostapd.pid

trap cleanup EXIT

dhcpd_start

while sleep 1 ; do

	TS_OLD=$(ls -l $LF)

	p2p_enable

	while sleep 1 ; do
		case $(p2p_get_status) in
			00)
				p2p_enable
				;;
			08 | 19 | 22)
				p2p_peer_scan && break
				p2p_disable
				;;
		esac
	done

	MAC=$(sudo iwpriv wlan0 p2p_get peer_deva | tr -d : | egrep '^[0-9A-Fa-f]{12}$' | cut --output-delimiter=: -c 1-2,3-4,5-6,7-8,9-10,11-12)

	sudo iwpriv wlan0 p2p_set got_wpsinfo=3

	#sudo iwpriv wlan0 p2p_get req_cm

	sudo iwpriv wlan0 p2p_set nego=$MAC

	while sleep 1 ; do
		case $(p2p_get_status) in
			10 | 19)
				break
				;;
		esac
	done

	hostapd_start

	while sleep 1 ; do
		sudo ./hostapd_cli wps_pbc any | grep -q OK && break
	done

	while sleep 1 ; do
		sudo ./hostapd_cli all_sta | grep -q dot11RSNAStatsSTAAddress && break
	done

	while sleep 1 ; do
		TS_NOW=$(ls -l $LF)
		if ! test "$TS_OLD" = "$TS_NEW" ; then
			IP=$(grep ^lease $LF | tail -n -1 | cut -d ' ' -f 2)
			echo IP=$IP
			test -z $IP || break
		fi
	done

	PORT=$(sudo iwpriv wlan0 p2p_get peer_port | grep ^Port= | cut -d= -f 2)
	echo PORT=$PORT

	# cvlc udp://@:50000 &
	./data.py &
	DATA_PID=$!

	sleep 1

	./control.py wlan0 $IP $PORT

	kill $DATA_PID

	hostapd_stop
done
