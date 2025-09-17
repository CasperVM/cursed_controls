use std::path::PathBuf;

fn main() {
    let lib_dir = PathBuf::from("src/360-w-raw-gadget");
    println!("cargo:rustc-link-search=native={}", lib_dir.display());
    println!("cargo:rustc-link-lib=static=360wgadget");
    println!("cargo:rerun-if-changed=src/360-raw-gadget/360wgadget.a");
}
