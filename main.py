import threading
import time
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.clock import Clock
from mycelium_node import MyceliumNode

class MyceliumDashboard(BoxLayout):
    def __init__(self, **kwargs):
        super(MyceliumDashboard, self).__init__(**kwargs)
        self.orientation = 'vertical'
        self.padding = 30
        self.spacing = 20

        # Initialize Master Mycelium Node
        self.node = MyceliumNode('mobile_node_prime', 250, 250, secret_key='mycelium-mesh-secret')
        self.node.register_peer_telemetry('laptop_bridge', 450, 450, latency_ms=28.5, packet_loss=0.01)
        self.node.rag.add_knowledge('chunk_prime_1', 'Verlet mesh network node active on Android.', [0.88, 0.11, 0.01])

        # UI Status Label
        self.status_label = Label(
            text='Initializing Mycelium v10.12 Mesh...',
            font_size=18,
            halign='center',
            valign='middle'
        )
        self.add_widget(self.status_label)

        # Trigger Swarm Query Button
        self.query_btn = Button(
            text='Broadcast Swarm RAG Query',
            size_hint=(1, 0.2),
            background_color=(0.1, 0.6, 0.4, 1)
        )
        self.query_btn.bind(on_press=self.trigger_swarm_query)
        self.add_widget(self.query_btn)

        # Schedule live physics & mesh tick
        Clock.schedule_interval(self.mesh_tick, 0.05)

    def mesh_tick(self, dt):
        # Update Verlet topology simulation step
        self.node.physics.step()
        state = self.node.status()
        
        nodes = state['physics_state']['nodes']
        links = state['physics_state']['links']
        
        self.status_label.text = (
            f"[ Mycelium Mesh Node: {state['node_id']} ]\n\n"
            f"Active Mesh Peers: {len(nodes) - 1}\n"
            f"Verlet Springs Active: {len(links)}\n"
            f"Local RAG Chunks: {state['rag_chunks_stored']}\n"
            f"Status: Synchronized & Operational ⚡"
        )

    def trigger_swarm_query(self, instance):
        # Execute secure signed swarm RAG lookup
        query_payload = {'query_vector': [0.85, 0.12, 0.03], 'max_results': 1}
        signed = self.node.rag.sign_query(query_payload)
        result = self.node.rag.verify_and_search(signed, [0.85, 0.12, 0.03], threshold=0.7)
        
        if result['matches']:
            match_text = result['matches'][0]['text']
            self.status_label.text = f"[ Swarm RAG Match Found ]\n\"{match_text}\""
        else:
            self.status_label.text = "[ Swarm RAG ] No matching peers found in range."

class MyceliumApp(App):
    def build(self):
        return MyceliumDashboard()

if __name__ == '__main__':
    MyceliumApp().run()
