#version 440
// I420 (YUV 4:2:0 planar) -> RGB, BT.709 limited range.  §0.4
//
// Three single-channel samplers, one matrix multiply. The GPU does for free what
// requesting RV32 from libVLC would have cost us on the CPU for every frame.
//
// Build:  pyside6-qsb --glsl "100 es,120,150" --hlsl 50 --msl 12 \
//                     -o yuv420p.frag.qsb yuv420p.frag
// (tools/build_shaders.py does this for you.)

layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4  qt_Matrix;
    float qt_Opacity;
} ubuf;

layout(binding = 1) uniform sampler2D y;
layout(binding = 2) uniform sampler2D u;
layout(binding = 3) uniform sampler2D v;

void main()
{
    // Limited-range (16-235 / 16-240) to full-range, per BT.709.
    float Y = texture(y, qt_TexCoord0).r - 0.0625;
    float U = texture(u, qt_TexCoord0).r - 0.5;
    float V = texture(v, qt_TexCoord0).r - 0.5;

    vec3 rgb;
    rgb.r = 1.1643 * Y + 1.7927 * V;
    rgb.g = 1.1643 * Y - 0.2132 * U - 0.5329 * V;
    rgb.b = 1.1643 * Y + 2.1124 * U;

    fragColor = vec4(clamp(rgb, 0.0, 1.0), 1.0) * ubuf.qt_Opacity;
}
