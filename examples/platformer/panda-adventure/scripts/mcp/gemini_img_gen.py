import os
from mcp.server.fastmcp import FastMCP
from typing import Annotated
from pydantic import Field
from pathlib import Path
from google import genai
from google.genai import types


mcp = FastMCP("gemini-nano-banana")
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

@mcp.tool()
def generate_image(
        prompt:Annotated[str,Field(
            description=("图像的详细描述。"
            "可以包含：主体内容、风格（写实/动漫/油画）、光线、构图、质量词（8k, detailed）。"
            "示例：'a futuristic Tokyo street at night, neon signs, heavy rain, "
            "cyberpunk style, photorealistic, 8k'")
        )],
        output_path:Annotated[str,Field(
            description="图片保存路径，需含文件名和扩展名，如 /tmp/result.png 或 ~/Desktop/output.png",
        )]="./generated_image.png",
        model:Annotated[str,Field(
            description=( "图生成模型选择：\n"
            "- gemini-3.1-flash-image-preview：Nano Banana 2，速度最快，日常首选\n"
            "- gemini-3-pro-image-preview：Nano Banana Pro，专业级质量\n"
            "- gemini-2.5-flash-image：Nano Banana 原版，轻量快速"),
        )]="gemini-3.1-flash-image-preview",
        aspect_ratio:Annotated[str,Field(
            description="宽高比。横屏用 16:9，竖屏/手机壁纸用 9:16，方图用 1:1，默认 1:1"
        )]="1:1",
        image_size:Annotated[str,Field(
            description="分辨率。可选 512 / 1K / 2K / 4K，默认 1K"
        )]="1K"
) -> str:
    '''
    根据用户的文字描述(prompt)，调用 Gemini 图像模型生成全新图片，并保存到本地。
    支持多种长宽比和分辨率。
    返回保存成功后的文件路径或生成失败的错误信息。
    '''

    try:
        response = client.models.generate_content(
            model = model,
            contents = [prompt],
            config = types.GenerateContentConfig(
                response_modalities=["TEXT","IMAGE"],
                image_config=types.ImageConfig(
                    aspect_ratio=aspect_ratio,
                    image_size=image_size
                )
            )
        )

        save_path = Path(output_path).expanduser().resolve()
        save_path.parent.mkdir(parents=True,exist_ok=True)
        result_texts=[]
        image_saved = False

        for part in response.parts:
            if part.text is not None:
                result_texts.append(part.text)
            elif part.inline_data is not None:
                image = part.as_image() # 官方推荐写法：part.as_image() 返回 PIL Image 对象
                image.save(str(save_path))
                result_texts.append(f"✅ 图片已保存至：{save_path}")
                image_saved = True

        if not image_saved:
            result_texts.append("⚠️ 未返回图像数据，请检查 prompt 是否违反内容政策")

        return "\n".join(result_texts)    
    
    except Exception as e:
        return f"❌ 生成失败：{type(e).__name__}: {str(e)}"

if __name__ == "__main__":
    mcp.run()