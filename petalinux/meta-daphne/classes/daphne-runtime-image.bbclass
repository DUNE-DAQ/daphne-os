ROOTFS_POSTPROCESS_COMMAND:append = " daphne_disable_nonruntime_services; "

daphne_disable_nonruntime_services() {
    # PetaLinux enables NFS server helpers by default in this KR260 image.
    # DAPHNE runtime images do not export NFS, and the generated nfsserver
    # unit fails on the board, masking the real service health signal.
    for unit in \
        nfs-server.service \
        nfs-mountd.service \
        nfs-statd.service \
        proc-fs-nfsd.mount \
        rpcbind.service \
        rpcbind.socket
    do
        find ${IMAGE_ROOTFS}${sysconfdir}/systemd/system \
            -type l -name "$unit" -delete 2>/dev/null || true
    done

    for svc in nfsserver nfscommon rpcbind; do
        find ${IMAGE_ROOTFS}${sysconfdir} \
            -path '*/rc*.d/S*'"$svc" -type l -delete 2>/dev/null || true
    done
}
