#!/usr/bin/env python
# -*- coding: UTF-8 -*-
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

"""a MiraCast sink implementation"""

import gobject
gobject.threads_init()
import pygst
pygst.require("0.10")
import gst
import pygtk
pygtk.require("2.0")
import gtk
gtk.gdk.threads_init()
import sys
import os
import socket
import re

class pyracastException(Exception):
    def __init__(self, reason):
        self.reason = reason

class pyracast:
    __name__ = "pyracast"
    __usage__ = "just start it"
    __def_win_size__ = (320, 240)

    had_pat = 0

    def createWindow(self):
        w = gtk.Window()
        w.set_size_request(*self.__def_win_size__)
        w.set_title(self.__name__)
        w.connect("destroy", gtk.main_quit)

        v = gtk.DrawingArea()
        v.modify_bg(gtk.STATE_NORMAL, v.style.black)

        w.add(v)
        w.show_all()

        return (w, v)

    def createPipeline(self, w):

        videosink = gst.element_factory_make("xvimagesink", "videosink")
        videosink.set_property("force-aspect-ratio", True)
        videosink.set_property("handle-expose", True)

        audiosink = gst.element_factory_make("alsasink", "audiosink")
        audioconvert = gst.element_factory_make("audioconvert", "audioconvert")

        videoqueue = gst.element_factory_make("queue", "videoqueue")
        audioqueue = gst.element_factory_make("queue", "audioqueue")

        # this code receives the messages from the pipeline. if we
        # need to set X11 id, then we call set_xid
        def bus_handler(bus, message):
            if message.type == gst.MESSAGE_ELEMENT:
                if message.structure.get_name() == 'prepare-xwindow-id':
                    #print("prepare-xwindow-id")
                    #print("src=%s" % message.src)
                    #try:
                    #    parent = message.src.get_parent()
                    #    print("parent=%s" % parent)
                    #    dcb = parent.get_by_name("bin")
                    #    print("dcb=%s" % dcb)
                    #    sps = dcb.src_pads()
                    #    print("sps=%s" % sps)
                    #    sp = sps.next()
                    #    print("sp=%s" % sp)
                    #    caps = sp.get_caps()
                    #    print("caps=%s" % caps)
                    #except Exception, e:
                    #    print("e=%s" % e)
                    #    pass
                    #print("w=%s" % w)
                    #print("xid=%s" % w.window.xid)
                    gtk.gdk.threads_enter()
                    #message.src.set_xwindow_id(w.window.xid)
                    message.src.expose()
                    gtk.gdk.threads_leave()
            return gst.BUS_PASS

        # create our pipeline, and connect our bus_handler
        pipeline = gst.Pipeline("pipeline")
        bus = pipeline.get_bus()
        bus.set_sync_handler(bus_handler)

        pipeline.add(videosink, videoqueue, audiosink, audioconvert, audioqueue)
        videoqueue.link(videosink)
        audioconvert.link(audiosink)
        audioqueue.link(audioconvert)
        return (pipeline, (videoqueue, audioqueue))

    def magic(self, pipeline, (videoqueue, audioqueue)):

        try:
            dcb = gst.element_factory_make("decodebin2", "dcb")
        except:
            dcb = gst.element_factory_make("decodebin", "dcb")

        pipeline.add(dcb)

        pr, pw = os.pipe()

        src = gst.element_factory_make("fdsrc", "fdsrc")
        src.set_property("fd", pr)
        src.set_property("blocksize", 188)
        #src.set_property("caps", gst.Caps('video/mpegts,packetsize=(int)188'))

        pipeline.add(src)

        def onPadAdded(source, pad):
            #print("source=%s, pad=%s" % (source, pad))
            for sink in [videoqueue, audioqueue]:
                #print("trying sink=%s" % sink)
                tpad = sink.get_compatible_pad(pad)
                if tpad:
                    #print("got tpad=%s" % tpad)
                    try:
                        pad.link(tpad)
                        #print("linked source=%s, pad=%s to sink=%s, tpad=%s" % (source, pad, sink, tpad))
                        return
                    except:
                        pass

        dcb.connect("pad-added", onPadAdded)

        src.link(dcb)

        self.pfd = os.fdopen(pw, 'w')
        #self.pfd = open('data.m2ts', 'w')

    def get_pcr_ms(self, p):
        pcr = 0
        for b in p:
            pcr = (pcr << 8) | b

        pcr_base = pcr >> (6+9)
        pcr_ext = pcr & 0x1ff
        pcr = pcr_base * 300 + pcr_ext

        pcr_ms = pcr / 27000

        return pcr_ms

    crc_tab = [
        0x00000000, 0x04c11db7, 0x09823b6e, 0x0d4326d9, 0x130476dc, 0x17c56b6b,
        0x1a864db2, 0x1e475005, 0x2608edb8, 0x22c9f00f, 0x2f8ad6d6, 0x2b4bcb61,
        0x350c9b64, 0x31cd86d3, 0x3c8ea00a, 0x384fbdbd, 0x4c11db70, 0x48d0c6c7,
        0x4593e01e, 0x4152fda9, 0x5f15adac, 0x5bd4b01b, 0x569796c2, 0x52568b75,
        0x6a1936c8, 0x6ed82b7f, 0x639b0da6, 0x675a1011, 0x791d4014, 0x7ddc5da3,
        0x709f7b7a, 0x745e66cd, 0x9823b6e0, 0x9ce2ab57, 0x91a18d8e, 0x95609039,
        0x8b27c03c, 0x8fe6dd8b, 0x82a5fb52, 0x8664e6e5, 0xbe2b5b58, 0xbaea46ef,
        0xb7a96036, 0xb3687d81, 0xad2f2d84, 0xa9ee3033, 0xa4ad16ea, 0xa06c0b5d,
        0xd4326d90, 0xd0f37027, 0xddb056fe, 0xd9714b49, 0xc7361b4c, 0xc3f706fb,
        0xceb42022, 0xca753d95, 0xf23a8028, 0xf6fb9d9f, 0xfbb8bb46, 0xff79a6f1,
        0xe13ef6f4, 0xe5ffeb43, 0xe8bccd9a, 0xec7dd02d, 0x34867077, 0x30476dc0,
        0x3d044b19, 0x39c556ae, 0x278206ab, 0x23431b1c, 0x2e003dc5, 0x2ac12072,
        0x128e9dcf, 0x164f8078, 0x1b0ca6a1, 0x1fcdbb16, 0x018aeb13, 0x054bf6a4,
        0x0808d07d, 0x0cc9cdca, 0x7897ab07, 0x7c56b6b0, 0x71159069, 0x75d48dde,
        0x6b93dddb, 0x6f52c06c, 0x6211e6b5, 0x66d0fb02, 0x5e9f46bf, 0x5a5e5b08,
        0x571d7dd1, 0x53dc6066, 0x4d9b3063, 0x495a2dd4, 0x44190b0d, 0x40d816ba,
        0xaca5c697, 0xa864db20, 0xa527fdf9, 0xa1e6e04e, 0xbfa1b04b, 0xbb60adfc,
        0xb6238b25, 0xb2e29692, 0x8aad2b2f, 0x8e6c3698, 0x832f1041, 0x87ee0df6,
        0x99a95df3, 0x9d684044, 0x902b669d, 0x94ea7b2a, 0xe0b41de7, 0xe4750050,
        0xe9362689, 0xedf73b3e, 0xf3b06b3b, 0xf771768c, 0xfa325055, 0xfef34de2,
        0xc6bcf05f, 0xc27dede8, 0xcf3ecb31, 0xcbffd686, 0xd5b88683, 0xd1799b34,
        0xdc3abded, 0xd8fba05a, 0x690ce0ee, 0x6dcdfd59, 0x608edb80, 0x644fc637,
        0x7a089632, 0x7ec98b85, 0x738aad5c, 0x774bb0eb, 0x4f040d56, 0x4bc510e1,
        0x46863638, 0x42472b8f, 0x5c007b8a, 0x58c1663d, 0x558240e4, 0x51435d53,
        0x251d3b9e, 0x21dc2629, 0x2c9f00f0, 0x285e1d47, 0x36194d42, 0x32d850f5,
        0x3f9b762c, 0x3b5a6b9b, 0x0315d626, 0x07d4cb91, 0x0a97ed48, 0x0e56f0ff,
        0x1011a0fa, 0x14d0bd4d, 0x19939b94, 0x1d528623, 0xf12f560e, 0xf5ee4bb9,
        0xf8ad6d60, 0xfc6c70d7, 0xe22b20d2, 0xe6ea3d65, 0xeba91bbc, 0xef68060b,
        0xd727bbb6, 0xd3e6a601, 0xdea580d8, 0xda649d6f, 0xc423cd6a, 0xc0e2d0dd,
        0xcda1f604, 0xc960ebb3, 0xbd3e8d7e, 0xb9ff90c9, 0xb4bcb610, 0xb07daba7,
        0xae3afba2, 0xaafbe615, 0xa7b8c0cc, 0xa379dd7b, 0x9b3660c6, 0x9ff77d71,
        0x92b45ba8, 0x9675461f, 0x8832161a, 0x8cf30bad, 0x81b02d74, 0x857130c3,
        0x5d8a9099, 0x594b8d2e, 0x5408abf7, 0x50c9b640, 0x4e8ee645, 0x4a4ffbf2,
        0x470cdd2b, 0x43cdc09c, 0x7b827d21, 0x7f436096, 0x7200464f, 0x76c15bf8,
        0x68860bfd, 0x6c47164a, 0x61043093, 0x65c52d24, 0x119b4be9, 0x155a565e,
        0x18197087, 0x1cd86d30, 0x029f3d35, 0x065e2082, 0x0b1d065b, 0x0fdc1bec,
        0x3793a651, 0x3352bbe6, 0x3e119d3f, 0x3ad08088, 0x2497d08d, 0x2056cd3a,
        0x2d15ebe3, 0x29d4f654, 0xc5a92679, 0xc1683bce, 0xcc2b1d17, 0xc8ea00a0,
        0xd6ad50a5, 0xd26c4d12, 0xdf2f6bcb, 0xdbee767c, 0xe3a1cbc1, 0xe760d676,
        0xea23f0af, 0xeee2ed18, 0xf0a5bd1d, 0xf464a0aa, 0xf9278673, 0xfde69bc4,
        0x89b8fd09, 0x8d79e0be, 0x803ac667, 0x84fbdbd0, 0x9abc8bd5, 0x9e7d9662,
        0x933eb0bb, 0x97ffad0c, 0xafb010b1, 0xab710d06, 0xa6322bdf, 0xa2f33668,
        0xbcb4666d, 0xb8757bda, 0xb5365d03, 0xb1f740b4
    ]

    def crc32(self, buf):
        crc = 0xFFFFFFFF
        for b in buf:
            crc = ((crc & 0xFFFFFF) << 8) ^ self.crc_tab[((crc & 0xFF000000) >> 24) ^ b]
        return crc

    def handle_ts_packet(self, p):
        pusi = p[1] >> 6 & 0b1
        pid = ((p[1] << 8) | p[2]) & 0x1fff
        af = p[3] >> 5 & 0b1
        pl = p[3] >> 4 & 0b1

        s = ''

        #if pusi or af or not pl:
        #    s = s + ("\npusi=%1d af=%1d pl=%1d " % (pusi,af,pl))

        pl = p[4:]

        if af:
            afl = pl[0]
            aff = pl[1]
            af = pl[2:afl+1]
            pl = pl[afl+1:]
            if aff & 0b00010000:
                # PCR
                pcr = self.get_pcr_ms(af[0:6])
                af = af[6:]
                #s = s + ("pcr=%f ms " % pcr)
            if aff & 0b00001000:
                # OPCR
                opcr = self.get_pcr_ms(af[0:6])
                af = af[6:]
                #s = s + ("opcr=%f ms " % opcr)

        if pid == 0x0000:
            s = s + '+'
            self.had_pat = 1
            pass
        elif pid == 0x0100:
            s = s + '#'
            if p[5] == 0x02: # PMT
                pmt_len = ((p[6] << 8) | p[7]) & 0x0fff
                if p[0x20] == 0x83:
                    #crc = self.crc32(p[5:5+3+pmt_len])
                    #s = s + "\n" + ('CRC1: CRC=%08X' % crc) + "\n"
                    #for i in range(len(pmt)):
                    #    s = s + ("\n" if i % 16 == 0 else " ")
                    #    s = s + ("%02x" % pmt[i])
                    #s = s + "\n"
                    p[0x20] = 0x8b
                    crc = self.crc32(p[5:5+3+pmt_len-4])
                    p[5+3+pmt_len-4] = crc >> 24
                    p[5+3+pmt_len-3] = crc >> 16 & 0xFF
                    p[5+3+pmt_len-2] = crc >> 8 & 0xFF
                    p[5+3+pmt_len-1] = crc & 0xFF
                    #crc = self.crc32(p[5:5+3+pmt_len])
                    #s = s + ('CRC2: CRC=%08X' % crc) + "\n"
        elif pid == 0x1000:
            s = s + 'P'
            pass
        elif pid == 0x1011:
            s = s + 'V'
            if pusi:
                pes_ext_len = (pl[4] << 8) + pl[5]
                #s = s + "pes_ext_len=%d" % pes_ext_len
                assert(pl[8] == 0x05)
            pass
        elif pid == 0x1100:
            s = s + 'A'
            pass
        else:
            s = s + ("\nunknown pid %x" % pid)
            for i in range(len(p)):
                s = s + ("\n" if i % 16 == 0 else " ")
                s = s + ("%02x" % p[i])
            s = s + "\n"

        sys.stderr.write(s)
        if self.had_pat:
            self.pfd.write(p)
            self.p.set_state(gst.STATE_PLAYING)

    def onSrcIn(self, src, cond):
        sys.stderr.write('T')

        p = self.src.recv(2048)

        assert(len(p) > 12)
        p = p[12:]

        assert len(p) % 188 == 0

        while len(p) > 0:
            self.handle_ts_packet(bytearray(p[0:188]))
            p = p[188:]

        return True

    def run(self):
        self.src = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.src.bind(('192.168.2.254',50000))
        print("socket bound")
        v = None
        #w, v = self.createWindow()
        self.p, s = self.createPipeline(v)
        try:
            self.magic(self.p, s)
            self.p.set_state(gst.STATE_PLAYING)
            print("pipeline playing")
            self.src_id = gobject.io_add_watch(self.src, gobject.IO_IN, self.onSrcIn)
            print("entering main()")
            gtk.main()
        except pyracastException, e:
            print e.reason
            print self.__usage__
            sys.exit(-1)

if __name__ == '__main__':
    pyracast().run()
