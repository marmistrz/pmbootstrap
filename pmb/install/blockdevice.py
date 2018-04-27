"""
Copyright 2018 Oliver Smith

This file is part of pmbootstrap.

pmbootstrap is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

pmbootstrap is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with pmbootstrap.  If not, see <http://www.gnu.org/licenses/>.
"""
import logging
import os
import glob
import pmb.helpers.mount
import pmb.install.losetup
import pmb.helpers.cli
import pmb.config


def previous_install(args):
    """
    Search the sdcard for possible existence of a previous installation of pmOS.
    We temporarily mount the possible pmOS_boot partition as /dev/sdcardp1 inside
    the native chroot to check the label from there.
    """
    label = ""
    for blockdevice_outside in [args.sdcard + "1", args.sdcard + "p1"]:
        if not os.path.exists(blockdevice_outside):
            continue
        blockdevice_inside = "/dev/sdcardp1"
        pmb.helpers.mount.bind_blockdevice(args, blockdevice_outside,
                                           args.work + "/chroot_native" + blockdevice_inside)
        label = pmb.chroot.root(args, ["blkid", "-s", "LABEL", "-o", "value",
                                blockdevice_inside], return_stdout=True)
        pmb.helpers.run.root(args, ["umount", args.work + "/chroot_native" + blockdevice_inside])
    return "pmOS_boot" in label


def mount_sdcard(args):
    # Sanity checks
    if args.deviceinfo["external_storage"] != "true":
        raise RuntimeError("According to the deviceinfo, this device does"
                           " not support a sdcard installation.")
    if not os.path.exists(args.sdcard):
        raise RuntimeError("The sdcard device does not exist: " +
                           args.sdcard)
    for path in glob.glob(args.sdcard + "*"):
        if pmb.helpers.mount.ismount(path):
            raise RuntimeError(path + " is mounted! We will not attempt"
                               " to format this!")
    logging.info("(native) mount /dev/install (host: " + args.sdcard + ")")
    pmb.helpers.mount.bind_blockdevice(args, args.sdcard,
                                       args.work + "/chroot_native/dev/install")
    if previous_install(args):
        if not pmb.helpers.cli.confirm(args, "WARNING: This device has a"
                                       " previous installation of pmOS."
                                       " CONTINUE?"):
            raise RuntimeError("Aborted.")
    else:
        if not pmb.helpers.cli.confirm(args, "EVERYTHING ON " + args.sdcard +
                                       " WILL BE ERASED! CONTINUE?"):
            raise RuntimeError("Aborted.")


def create_and_mount_image(args, size_boot, size_root):
    """
    Create a new image file, and mount it as /dev/install.

    :param size_boot: size of the boot partition in bytes
    :param size_root: size of the root partition in bytes
    """
    # Short variables for paths
    chroot = args.work + "/chroot_native"
    img_path_full = "/home/pmos/rootfs/" + args.device + ".img"
    img_path_outside_full = chroot + img_path_full
    img_path_boot = "/home/pmos/rootfs/" + args.device + "-boot.img"
    img_path_outside_boot = chroot + img_path_boot
    img_path_root = "/home/pmos/rootfs/" + args.device + "-root.img"
    img_path_outside_root = chroot + img_path_root

    # Umount and delete existing images
    for img_path, img_path_outside in [[img_path_full, img_path_outside_full],
                                       [img_path_boot, img_path_outside_boot],
                                       [img_path_root, img_path_outside_root]]:
        if os.path.exists(img_path_outside):
            pmb.helpers.mount.umount_all(args, chroot + "/mnt")
            pmb.install.losetup.umount(args, img_path)
            pmb.chroot.root(args, ["rm", img_path])
            if os.path.exists(img_path_outside):
                raise RuntimeError("Failed to remove old image file: " +
                                   img_path_outside)

    # Make sure there is enough free space
    size_mb = round((size_boot + size_root) / (1024**2))
    disk_data = os.statvfs(args.work)
    free = round((disk_data.f_bsize * disk_data.f_bavail) / (1024**2))
    if size_mb > free:
        raise RuntimeError("Not enough free space to create rootfs image! (free: " + str(free) + "M, required: " + str(size_mb) + "M)")

    # Create empty image files
    pmb.chroot.user(args, ["mkdir", "-p", "/home/pmos/rootfs"])
    if not args.split:
        size_mb_full = str(size_mb) + "M"
        logging.info("(native) create " + args.device + ".img (" + size_mb_full + ")")
        pmb.chroot.root(args, ["truncate", "-s", size_mb_full, img_path_full])
    else:
        size_mb_boot = str(round(size_boot / (1024**2))) + "M"
        size_mb_root = str(round(size_root / (1024**2))) + "M"
        logging.info("(native) create " + args.device + "-boot.img (" + size_mb_boot + ")")
        pmb.chroot.root(args, ["truncate", "-s", size_mb_boot, img_path_boot])
        logging.info("(native) create " + args.device + "-root.img (" + size_mb_root + ")")
        pmb.chroot.root(args, ["truncate", "-s", size_mb_root, img_path_root])

    # Mount to /dev/install
    mount_image_paths = list()
    if not args.split:
        mount_image_paths.append([img_path_full, "/dev/install"])
    else:
        mount_image_paths.append([img_path_boot, "/dev/install-boot"])
        mount_image_paths.append([img_path_root, "/dev/install-root"])

    for img_path, mount_point in mount_image_paths:
        logging.info("(native) mount " + mount_point +
                     " (" + os.path.basename(img_path) + ")")
        pmb.install.losetup.mount(args, img_path)
        device = pmb.install.losetup.device_by_back_file(args, img_path)
        pmb.helpers.mount.bind_blockdevice(args, device, args.work +
                                           "/chroot_native" + mount_point)


def create(args, size_boot, size_root):
    """
    Create /dev/install (the "install blockdevice").

    :param size_boot: size of the boot partition in bytes
    :param size_root: size of the root partition in bytes
    """
    pmb.helpers.mount.umount_all(
        args, args.work + "/chroot_native/dev/install")
    if args.sdcard:
        mount_sdcard(args)
    else:
        create_and_mount_image(args, size_boot, size_root)
