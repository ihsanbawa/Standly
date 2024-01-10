{ pkgs }: {
  deps = [
    pkgs.postgresql
    pkgs.killall
  ];
}