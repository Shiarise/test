import sys
import os
import array
import struct
import random
import time
import threading

def getsizes(dev):
    """report media size and sector size for a device, platform specific code"""
    mediasize = 0       # bytes
    sectorsize = 4096   # bytes; educated guess

    try:
        # normal files, fails on block devices
        mediasize = os.stat(dev)[6]
    except IOError, (err_no, err_str):
        pass
    except:
        pass

    if mediasize:
        pass
    elif sys.platform == 'darwin':
        # mac os x ioctl from sys/disk.h
        DKIOCGETBLOCKSIZE = 0x40046418  # _IOR('d', 24, uint32_t)
        DKIOCGETBLOCKCOUNT = 0x40086419 # _IOR('d', 25, uint64_t)

        import fcntl
        fh = open(dev, 'r')
        buf = array.array('B', range(0,8))  # uint64
        r = fcntl.ioctl(fh.fileno(), DKIOCGETBLOCKCOUNT, buf, 1)
        blockcount = struct.unpack('Q', buf)[0]
        buf = array.array('B', range(0,4))  # uint32
        r = fcntl.ioctl(fh.fileno(), DKIOCGETBLOCKSIZE, buf, 1)
        sectorsize = struct.unpack('I', buf)[0]
        mediasize = sectorsize*blockcount
        fh.close()
        
    elif sys.platform.startswith('freebsd'):
        # freebsd ioctl from sys/disk.h
        DIOCGSECTORSIZE = 0x40046480  # _IOR('d', 128, uint32_t)
        DIOCGMEDIASIZE = 0x40086481 # _IOR('d', 129, uint64_t)
        
        import fcntl

        fh = open(dev, 'r')
        buf = array.array('B', range(0,4))  # uint32
        r = fcntl.ioctl(fh.fileno(), DIOCGSECTORSIZE, buf, 1)
        sectorsize = struct.unpack('I', buf)[0]
        buf = array.array('B', range(0,8))  # off_t / int64
        r = fcntl.ioctl(fh.fileno(), DIOCGMEDIASIZE, buf, 1)
        mediasize = struct.unpack('q', buf)[0]
        fh.close()

    elif sys.platform == 'win32':
        sectorsize = 512 # fixme
        # win32 ioctl from winioctl.h, requires pywin32
        try:
            import win32file
        except ImportError:
            raise SystemExit("Package pywin32 not found, see http://sf.net/projects/pywin32/")
        IOCTL_DISK_GET_DRIVE_GEOMETRY = 0x00070000
        dh = win32file.CreateFile(dev, 0, win32file.FILE_SHARE_READ, None, win32file.OPEN_EXISTING, 0, None)
        info = win32file.DeviceIoControl(dh, IOCTL_DISK_GET_DRIVE_GEOMETRY, '', 24)
        win32file.CloseHandle(dh)
        (cyl_lo, cyl_hi, media_type, tps, spt, bps) = struct.unpack('6L', info)
        mediasize = ((cyl_hi << 32) + cyl_lo) * tps * spt * bps

    elif sys.platform == 'linux2':
        # https://people.redhat.com/msnitzer/docs/io-limits.txt
        # linux/fs.h
        BLKGETSIZE64=0x80081272 # _IOR(0x12,114,size_t)
        BLKGETSIZE=0x1260
        BLKPBSZGET=0x127b # _IO(0x12,123)

        import fcntl
        fh = open(dev, 'r')
        buf = array.array('B', range(0,4))  # int32
        r = fcntl.ioctl(fh.fileno(), BLKPBSZGET, buf, 1)
        sectorsize = struct.unpack('I', buf)[0]
        try:
            buf = array.array('B', range(0,8))  # u64
            r = fcntl.ioctl(fh.fileno(), BLKGETSIZE64, buf, 1)
            mediasize = struct.unpack('Q', buf)[0]
        except IOError, (err_no, err_str):
            buf = array.array('B', range(0,4))  # u32
            r = fcntl.ioctl(fh.fileno(), BLKGETSIZE, buf, 1)
            mediasize = struct.unpack('I', buf)[0]*512
        fh.close()
    else:
        raise Exception("platform specific code not present for %s" % sys.platform)

    return mediasize, sectorsize

def greek(value, precision=0, prefix=None):
    """Return a string representing the IEC or SI suffix of a value"""
    # Copyright (c) 1999 Martin Pohl, copied from
    # http://mail.python.org/pipermail/python-list/1999-December/018519.html
    if prefix=='machine-readable':
        _abbrevs = [ (1     , ' ') ]
    elif prefix=='si':
        # Use SI (10-based) units
        _abbrevs = [
            (10**15, 'P'),
            (10**12, 'T'),
            (10** 9, 'G'),
            (10** 6, 'M'),
            (10** 3, 'k'),
            (1     , ' ')
        ]
    else:
        # Use IEC (2-based) units
        _abbrevs = [
            (1<<50L, 'Pi'),
            (1<<40L, 'Ti'),
            (1<<30L, 'Gi'),
            (1<<20L, 'Mi'),
            (1<<10L, 'Ki'),
            (1     , '  ')
        ]

    for factor, suffix in _abbrevs:
        if value >= factor:
            break

    if precision == 0:
        return '%3.d %s' % (int(value/factor), suffix)
    else:
        fmt='%%%d.%df %%s' % (4+precision, precision)
        return fmt % (float(value)/factor, suffix)

def iops(dev, blocksize=512, pattern='random', t=2):
    """measure input/output operations per second
    Perform random 512b aligned reads of blocksize bytes on fh for t seconds
    and print a stats line
    Returns: IOs/s
    """

    fh = open(dev, 'r')
    count = 0
    start = time.time()
    while time.time() < start+t:
        count += 1
        if pattern=='random':
            pos = random.randint(0, mediasize - blocksize) # need at least one block left
            pos &= ~(sectorsize-1)   # sector alignment at blocksize
            fh.seek(pos)
        blockdata = fh.read(blocksize)
        # check wraparound
        if len(blockdata) == 0 and pattern=='sequential':
            os.lseek(fd, 0, os.SEEK_SET)
    end = time.time()

    t = end - start

    fh.close()

    return count/t


if __name__ == '__main__':
    # parse cli
    t = 2                       # seconds
    num_threads = 32            # threads
    blocksize = 512             # bytes
    units='si'                  # si|machine-readable
    dev = None                  # /dev/sda
    exact_blocksize = False
    pattern='random'            # random|sequential
    sectorsize=0
    mediasize=0

    if len(sys.argv) < 2:
        raise SystemExit(USAGE)

    while sys.argv:
        arg = sys.argv.pop(0)
        if arg in ['-n', '--num-threads']:
            num_threads = int(sys.argv.pop(0))
        elif arg in ['-t', '--time']:
            t = int(sys.argv.pop(0))
        elif arg in ['-m', '--machine-readable']:
	    units = 'machine-readable'
        elif arg in ['-b', '--block-size']:
            blocksize = int(sys.argv.pop(0))
            exact_blocksize = True
        elif arg in ['--override-sector-size']:
	    sectorsize = int(sys.argv.pop(0))
        elif arg in ['--override-media-size']:
            mediasize = int(sys.argv.pop(0))
        elif arg in ['-p', '--pattern']:
            pattern = sys.argv.pop(0)
            if not pattern in ['random', 'sequential']:
                raise SystemExit("unknown pattern: %s" % pattern)
        else:
            dev = arg

    # run benchmark
    try:
	if (not (sectorsize > 0 and mediasize > 0)):
             mediasize, sectorsize = getsizes(dev)
	else:
	     print "sectorsize and mediasize override"
        print "%s, %s, sectorsize=%dB, #threads=%d, pattern=%s:" % (dev, greek(mediasize, 2, units), sectorsize, num_threads, pattern)
        _iops = num_threads+1 # initial loop
        while _iops > max(1, num_threads/4) and blocksize < mediasize:
            # threading boilerplate
            threads = []
            results = []
            
            def results_wrap(results, func, *__args, **__kw):
                """collect return values from func"""
                result = func(*__args, **__kw)
                results.append(result)

            for i in range(0, num_threads):
                _t = threading.Thread(target=results_wrap,
                                      args=(results, iops, dev, blocksize, pattern, t,))
                _t.start()
                threads.append(_t)

            for _t in threads:
                _t.join()
            _iops = sum(results)

            bandwidth = int(blocksize*_iops)
            print " %sB blocks: %6.1f IO/s, %sB/s (%sbit/s)" % (greek(blocksize, 0, units), _iops,
                greek(bandwidth, 1, units), greek(8*bandwidth, 1, units))

            if exact_blocksize:
                break
            blocksize *= 2

    except IOError, (err_no, err_str):
        raise SystemExit(err_str)
    except KeyboardInterrupt:
        raise SystemExit("caught ctrl-c, bye.")
