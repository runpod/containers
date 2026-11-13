//! GPU check for the Runpod Burn image: runs the same matmul on Burn's CUDA and
//! Vulkan backends and compares each result with the CPU (Flex) backend.
//!
//! Run `cargo run --release` to check both, or pass `cuda` or `vulkan` to check one.

use burn::prelude::*;
use burn::tensor::{Distribution, Tolerance};

const SIZE: usize = 1024;

fn matmul(device: &Device, lhs: &TensorData, rhs: &TensorData) -> TensorData {
    let lhs = Tensor::<2>::from_data(lhs.clone(), device);
    let rhs = Tensor::<2>::from_data(rhs.clone(), device);
    lhs.matmul(rhs).into_data()
}

fn check(name: &str, device: Device, lhs: &TensorData, rhs: &TensorData, expected: &TensorData) {
    let started = std::time::Instant::now();
    let got = matmul(&device, lhs, rhs);
    got.assert_approx_eq::<f32>(expected, Tolerance::rel_abs(1e-2, 1e-2));
    println!("{name}: OK ({SIZE}x{SIZE} matmul matches CPU, {:?})", started.elapsed());
}

fn main() {
    let only = std::env::args().nth(1);
    let cpu = Device::flex();
    let lhs = Tensor::<2>::random([SIZE, SIZE], Distribution::Default, &cpu).into_data();
    let rhs = Tensor::<2>::random([SIZE, SIZE], Distribution::Default, &cpu).into_data();
    let expected = matmul(&cpu, &lhs, &rhs);

    if only.as_deref().is_none_or(|b| b == "cuda") {
        check("cuda", Device::cuda(0), &lhs, &rhs, &expected);
    }
    if only.as_deref().is_none_or(|b| b == "vulkan") {
        check("vulkan", Device::vulkan(Default::default()), &lhs, &rhs, &expected);
    }
}
