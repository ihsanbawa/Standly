{ pkgs }: {
  deps = [
    pkgs.mailutils
    pkgs.postgresql
    pkgs.killall
  ];
}