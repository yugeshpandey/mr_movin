import gradio as gr
from chatbot import chat

# Intro message shown when the app loads or when the user clears the chat
INTRO_MESSAGE = (
    "Hi there! I'm Mr. Movin', your Apartment Relocation Assistant.\n\n"
    "I can help you explore cities and metros based on rent data.\n"
    "Try things like:\n"
    "• \"I have a $2,500 budget and want an apartment in California.\"\n"
    "• \"Show me some of the cheapest metros in the US.\"\n"
    "• \"Compare Seattle, WA and Austin, TX.\"\n"
    "• \"What are some up-and-coming rental markets over the last 3 years?\""
)


def respond(message, history):
    history = history or []

    # Call your core chat function — it returns a string reply
    reply = chat(message, history)

    # Append user and assistant messages in the expected format
    history.append({"role": "user", "content": message})
    history.append({"role": "assistant", "content": reply})

    # Return updated history and clear the input box
    return history, ""


def reset_chat():
    """
    Reset chat history back to just the assistant intro message
    and clear the input box.
    """
    return [{"role": "assistant", "content": INTRO_MESSAGE}], ""


with gr.Blocks() as demo:
    gr.Markdown(
        "# MR. MOVIN' - Apartment Relocation Assistant\n"
        "Ask about your monthly rent budget, cheapest metros, or compare cities."
    )

    # Start the chatbot with a greeting from the assistant
    chatbot = gr.Chatbot(
        value=[{"role": "assistant", "content": INTRO_MESSAGE}],
        height=400,
        show_label=False,
    )
    msg = gr.Textbox(
        placeholder="Example: I have a $2500 budget in IL.",
        label="Your message",
    )
    clear = gr.Button("Clear chat")

    msg.submit(respond, [msg, chatbot], [chatbot, msg])
    clear.click(reset_chat, None, [chatbot, msg])

if __name__ == "__main__":
    demo.launch(theme='shivi/calm_seafoam')
