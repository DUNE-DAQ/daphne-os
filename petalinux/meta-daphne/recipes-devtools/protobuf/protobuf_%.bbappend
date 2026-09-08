# The upstream target recipe builds libprotoc but disables the protoc binary
# by default. Installing protobuf-compiler alone therefore does not provide
# an on-board compiler. Keep this opt-in for the developer image profile.
PACKAGECONFIG:append:class-target = " ${@bb.utils.contains('DAPHNE_IMAGE_PROFILE', 'developer', 'compiler', '', d)}"
