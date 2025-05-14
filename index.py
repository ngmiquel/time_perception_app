import tkinter as tk
from tkinter import PhotoImage
import time
import csv
import os
import pygame
import json
from tkinter import messagebox, simpledialog, ttk, Menu
from PIL import Image, ImageTk, ImageSequence
import pandas as pd

# Librerías para BLE (para la conexión con el pulsómetro)
import asyncio
import threading
from bleak import BleakClient, BleakScanner

# UUID estándar para el servicio y característica de Heart Rate en BLE
HR_SERVICE_UUID = "0000180d-0000-1000-8000-00805f9b34fb"
HR_MEASUREMENT_CHAR_UUID = "00002a37-0000-1000-8000-00805f9b34fb"


class HeartRateMonitor:
    def __init__(self, address):
        self.address = address
        self.current_hr = 0
        self.loop = None
        self.thread = None
        self.running = False

    def notification_handler(self, sender: int, data: bytearray):
        if len(data) > 1:
            # Se asume que el segundo byte contiene la FC (8 bits)
            self.current_hr = data[1]

    async def run(self):
        async with BleakClient(self.address) as client:
            print("Conectado a:", self.address)
            await client.start_notify(HR_MEASUREMENT_CHAR_UUID, self.notification_handler)
            while self.running:
                await asyncio.sleep(1)
            await client.stop_notify(HR_MEASUREMENT_CHAR_UUID)
        print("Desconectado de:", self.address)

    def start(self):
        self.running = True
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run_loop)
        self.thread.start()

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.run())

    def stop(self):
        self.running = False
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)
        if self.thread:
            self.thread.join()
        self.loop = None
        self.thread = None


class StopwatchApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Testing Time Estimation")
        self.root.geometry("600x500")
        self.root.configure(bg="#E8F6F3")

        pygame.mixer.init()
        self.initialize_paths()
        self.initialize_variables()
        self.create_ui_elements()
        self.create_menu()
        self.create_csv_file_if_not_exists()
        self.bind_keys()

        # Inicialmente, ningún dispositivo HR está conectado
        self.hr_monitor = None
        self.hr_rest = None  # Aquí se almacenará el HR en reposo

        # Actualiza la etiqueta de HR en tiempo real
        self.update_hr_label()

    def initialize_paths(self):
        current_directory = os.path.dirname(os.path.abspath(__file__))
        # Subcarpetas
        assets_directory = os.path.join(current_directory, 'assets')
        data_directory   = os.path.join(current_directory, 'data')
        # Rutas de archivos en assets/
        self.clock_image_path = os.path.join(assets_directory, 'clock.png')
        self.clock_gif_path   = os.path.join(assets_directory, 'clock.gif')
        self.start_sound      = os.path.join(assets_directory, 'start.wav')
        # Rutas de archivos en data/
        self.participants_file = os.path.join(data_directory, 'participants.json')
        self.filename          = os.path.join(data_directory, 'time_data_collection.csv')
        # Guardamos los directorios para usarlos después
        self.assets_directory = assets_directory
        self.data_directory   = data_directory

    def initialize_variables(self):
        self.start_time = None
        self.running = False
        # Solo dos protocolos: CONTROL y HIGH
        self.protocols = ["CONTROL", "HIGH"]
        # El archivo de FC se definirá tras seleccionar el participante
        self.hr_filename = None
        # Carga de imágenes
        self.clock_image = PhotoImage(file=self.clock_image_path)
        self.clock_gif   = Image.open(self.clock_gif_path)
        self.clock_gif_frames = [
            ImageTk.PhotoImage(frame.copy().convert('RGBA'))
            for frame in ImageSequence.Iterator(self.clock_gif)
        ]
        self.current_frame_index = 0
        # Lista para guardar las lecturas de FC
        self.hr_readings = []

    def create_ui_elements(self):
        self.clock_label = tk.Label(self.root, image=self.clock_image, bg="#E8F6F3")
        self.clock_label.pack(pady=10)
        self.result_label = tk.Label(
            self.root,
            text="Select a participant and protocol, then press 'Confirm'",
            font=("Arial", 14, "bold"),
            bg="#E8F6F3"
        )
        self.result_label.pack(pady=10)
        input_frame = tk.Frame(self.root, bg="#E8F6F3")
        input_frame.pack(pady=10)
        self.select_participant_button = tk.Button(
            input_frame,
            text="Select Participant",
            command=self.select_participant,
            font=("Arial", 12),
            bg="#99CED3",
            fg="black",
            width=15
        )
        self.select_participant_button.grid(row=0, column=0, padx=5, pady=5)
        self.protocol_var = tk.StringVar(self.root)
        self.protocol_var.set("Select Protocol")
        self.protocol_menu = tk.OptionMenu(input_frame, self.protocol_var, *self.protocols)
        self.protocol_menu.config(width=15, font=("Arial", 12), bg="#99CED3", fg="black")
        self.protocol_menu.grid(row=0, column=1, padx=5, pady=5)
        button_frame = tk.Frame(self.root, bg="#E8F6F3")
        button_frame.pack(pady=10)
        self.confirm_button = tk.Button(
            button_frame,
            text="Confirm",
            command=self.confirm_data,
            font=("Arial", 12, "bold"),
            bg="#4CAF50",
            fg="white",
            width=10,
            state=tk.DISABLED
        )
        self.confirm_button.grid(row=0, column=0, padx=5, pady=5)
        self.start_button = tk.Button(
            button_frame,
            text="Start",
            command=self.start_stopwatch,
            font=("Arial", 12, "bold"),
            bg="#4CAF50",
            fg="white",
            state=tk.DISABLED,
            width=10
        )
        self.start_button.grid(row=0, column=1, padx=5, pady=5)
        self.cancel_button = tk.Button(
            button_frame,
            text="Cancel",
            command=self.cancel_test,
            font=("Arial", 12, "bold"),
            bg="#f44336",
            fg="white",
            state=tk.DISABLED,
            width=10
        )
        self.cancel_button.grid(row=0, column=2, padx=5, pady=5)
        # Etiqueta para la FC en tiempo real
        self.hr_label = tk.Label(
            self.root,
            text="HR: -- bpm",
            font=("Arial", 14, "bold"),
            bg="#E8F6F3",
            fg="#333"
        )
        self.hr_label.pack(pady=5)

    def create_menu(self):
        menubar = Menu(self.root)
        self.root.config(menu=menubar)
        participants_menu = Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Participants", menu=participants_menu)
        participants_menu.add_command(label="Add Participant", command=self.add_participant)
        participants_menu.add_command(label="View Participants", command=self.view_participants)
        participants_menu.add_command(label="Delete Participant", command=self.delete_participant)
        data_menu = Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Data", menu=data_menu)
        data_menu.add_command(label="View Data", command=self.view_data)
        data_menu.add_command(label="Delete Data Record", command=self.delete_data_record)
        data_menu.add_command(label="Export to Excel", command=self.export_to_excel)
        devices_menu = Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Devices", menu=devices_menu)
        devices_menu.add_command(label="Scan HR Device", command=self.scan_for_devices)
        devices_menu.add_command(label="Measure Resting HR", command=self.measure_resting_hr)
        exit_menu = Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Exit", menu=exit_menu)
        exit_menu.add_command(label="Exit Application", command=self.confirm_exit)

    def bind_keys(self):
        self.root.bind('<space>', self.stop_stopwatch)

    def create_csv_file_if_not_exists(self):
        if not os.path.exists(self.filename):
            with open(self.filename, mode='w', newline='', encoding='utf-8') as file:
                writer = csv.writer(file, delimiter=';')
                writer.writerow(['Participant', 'Protocol', 'Time (seconds)', 'RPE', 'Mean HR'])

    # ---------------------------------------------------------------------------
    #           MÉTODO PARA MEDIR HR REST EN REPOSO (3 minutos) Y ACTUALIZAR PARTICIPANTES
    # ---------------------------------------------------------------------------
    def measure_resting_hr(self):
        # Abre una ventana para elegir el participante al que medir HRrest
        if not os.path.exists(self.participants_file):
            messagebox.showwarning("No Participants", "No participants available.")
            return
        select_window = tk.Toplevel(self.root)
        select_window.title("Select Participant for Resting HR")
        select_window.geometry("600x400")
        select_window.configure(bg="#E8F6F3")
        with open(self.participants_file, 'r') as file:
            participants = json.load(file)
        if not participants:
            messagebox.showwarning("No Participants", "No participants available.")
            return
        tree = ttk.Treeview(select_window, selectmode='browse')
        tree['columns'] = ('First Name', 'Last Name', 'Birth Date', 'Sex')
        tree.column('#0', width=0, stretch=tk.NO)
        tree.column('First Name', anchor=tk.W, width=100)
        tree.column('Last Name', anchor=tk.W, width=100)
        tree.column('Birth Date', anchor=tk.CENTER, width=100)
        tree.column('Sex', anchor=tk.CENTER, width=100)
        tree.heading('#0', text='', anchor=tk.W)
        tree.heading('First Name', text='First Name', anchor=tk.W)
        tree.heading('Last Name', text='Last Name', anchor=tk.W)
        tree.heading('Birth Date', text='Birth Date', anchor=tk.CENTER)
        tree.heading('Sex', text='Sex', anchor=tk.CENTER)
        for i, participant in enumerate(participants):
            tree.insert('', 'end', iid=i, values=(
                participant['First Name'],
                participant['Last Name'],
                participant['Birth Date'],
                participant['Sex']
            ))
        tree.pack(pady=10, padx=10, fill='both', expand=True)
        def confirm_selection():
            selected_item = tree.selection()
            if not selected_item:
                messagebox.showwarning("Warning", "Please select a participant.")
                return
            participant_index = int(selected_item[0])
            self.selected_resting_participant = participants[participant_index]
            select_window.destroy()
            self.start_resting_hr_measurement()
        select_button = tk.Button(select_window, text="Select", command=confirm_selection,
                                   font=("Arial", 12, "bold"), bg="#4CAF50", fg="white")
        select_button.pack(pady=20)

    def start_resting_hr_measurement(self):
        if not self.hr_monitor:
            messagebox.showwarning("No HR Device", "Please connect a HR device first (via Devices > Scan HR Device).")
            return
        measure_window = tk.Toplevel(self.root)
        measure_window.title("Measure Resting HR")
        measure_window.geometry("400x200")
        measure_window.configure(bg="#E8F6F3")
        instructions = tk.Label(measure_window,
                                  text="Please sit calmly for 3 minutes.\nMeasuring resting HR...",
                                  font=("Arial", 12), bg="#E8F6F3")
        instructions.pack(pady=10)
        timer_label = tk.Label(measure_window,
                               text="180 seconds remaining",
                               font=("Arial", 12, "bold"), bg="#E8F6F3")
        timer_label.pack(pady=10)
        hr_values = []
        total_time = 180  # 3 minutos
        def update_timer(remaining):
            if remaining <= 0:
                avg_hr = round(sum(hr_values) / len(hr_values), 2) if hr_values else 0
                self.update_participant_hrrest(self.selected_resting_participant, avg_hr)
                messagebox.showinfo("Measurement Complete", f"Resting HR measured: {avg_hr} bpm")
                measure_window.destroy()
            else:
                timer_label.config(text=f"{remaining} seconds remaining")
                hr_values.append(self.hr_monitor.current_hr)
                measure_window.after(1000, lambda: update_timer(remaining - 1))
        update_timer(total_time)

    def update_participant_hrrest(self, participant_record, hrrest_value):
        # Actualiza el campo "HRrest" en participants.json y en la variable interna
        if not os.path.exists(self.participants_file):
            return
        with open(self.participants_file, 'r') as file:
            participants = json.load(file)
        for participant in participants:
            if (participant.get("First Name") == participant_record.get("First Name") and
                participant.get("Last Name") == participant_record.get("Last Name") and
                participant.get("Birth Date") == participant_record.get("Birth Date")):
                participant["HRrest"] = hrrest_value
                break
        with open(self.participants_file, 'w') as file:
            json.dump(participants, file, indent=4)
        # Actualiza la variable interna para el HR en reposo
        self.hr_rest = hrrest_value

    # ---------------------------------------------------------------------------
    #                             PARTICIPANTES
    # ---------------------------------------------------------------------------
    def select_participant(self):
        select_window = tk.Toplevel(self.root)
        select_window.title("Select Participant")
        select_window.geometry("600x400")
        select_window.configure(bg="#E8F6F3")
        if not os.path.exists(self.participants_file):
            messagebox.showwarning("Warning", "No participants available.")
            return
        with open(self.participants_file, 'r') as file:
            participants = json.load(file)
        if not participants:
            messagebox.showwarning("Warning", "No participants available.")
            return
        tree = ttk.Treeview(select_window, selectmode='browse')
        tree['columns'] = ('First Name', 'Last Name', 'Birth Date', 'Sex')
        tree.column('#0', width=0, stretch=tk.NO)
        tree.column('First Name', anchor=tk.W, width=100)
        tree.column('Last Name', anchor=tk.W, width=100)
        tree.column('Birth Date', anchor=tk.CENTER, width=100)
        tree.column('Sex', anchor=tk.CENTER, width=100)
        tree.heading('#0', text='', anchor=tk.W)
        tree.heading('First Name', text='First Name', anchor=tk.W)
        tree.heading('Last Name', text='Last Name', anchor=tk.W)
        tree.heading('Birth Date', text='Birth Date', anchor=tk.CENTER)
        tree.heading('Sex', text='Sex', anchor=tk.CENTER)
        for i, participant in enumerate(participants):
            tree.insert('', 'end', iid=i, values=(
                participant['First Name'],
                participant['Last Name'],
                participant['Birth Date'],
                participant['Sex']
            ))
        tree.pack(pady=10, padx=10, fill='both', expand=True)
        def confirm_selection():
            selected_item = tree.selection()
            if not selected_item:
                messagebox.showwarning("Warning", "Please select a participant.")
                return
            participant_index = int(selected_item[0])
            participant = participants[participant_index]
            self.participant_var = f"{participant['First Name']} {participant['Last Name']}"
            self.result_label.config(text=f"Selected Participant: {self.participant_var}")
            self.confirm_button.config(state=tk.NORMAL)
            select_window.destroy()
            self.setup_hr_file()
        select_button = tk.Button(select_window, text="Select", command=confirm_selection,
                                   font=("Arial", 12, "bold"), bg="#4CAF50", fg="white")
        select_button.pack(pady=20)

    def setup_hr_file(self):
        if not hasattr(self, 'participant_var'):
            return
        filename = f"hr_data_{self.participant_var.replace(' ', '_')}.csv"
        self.hr_filename = os.path.join(self.data_directory, filename)
        if not os.path.exists(self.hr_filename):
            with open(self.hr_filename, 'w', newline='', encoding='utf-8') as file:
                writer = csv.writer(file, delimiter=';')
                writer.writerow(['Protocol', 'Elapsed Time (s)', 'HR (bpm)'])

    def add_participant(self):
        add_window = tk.Toplevel(self.root)
        add_window.title("Add Participant")
        add_window.geometry("400x300")
        add_window.configure(bg="#E8F6F3")
        form_frame = tk.Frame(add_window, bg="#E8F6F3")
        form_frame.pack(pady=10)
        first_name_label = tk.Label(form_frame, text="First Name:", font=("Arial", 12), bg="#E8F6F3")
        first_name_label.grid(row=0, column=0, sticky=tk.W, pady=5)
        first_name_entry = tk.Entry(form_frame, font=("Arial", 12))
        first_name_entry.grid(row=0, column=1, pady=5)
        last_name_label = tk.Label(form_frame, text="Last Name:", font=("Arial", 12), bg="#E8F6F3")
        last_name_label.grid(row=1, column=0, sticky=tk.W, pady=5)
        last_name_entry = tk.Entry(form_frame, font=("Arial", 12))
        last_name_entry.grid(row=1, column=1, pady=5)
        birth_label = tk.Label(form_frame, text="Birth Date (DD/MM/YYYY):", font=("Arial", 12), bg="#E8F6F3")
        birth_label.grid(row=2, column=0, sticky=tk.W, pady=5)
        birth_entry = tk.Entry(form_frame, font=("Arial", 12))
        birth_entry.grid(row=2, column=1, pady=5)
        sex_label = tk.Label(form_frame, text="Sex:", font=("Arial", 12), bg="#E8F6F3")
        sex_label.grid(row=3, column=0, sticky=tk.W, pady=5)
        sex_var = tk.StringVar(value="Select")
        sex_combobox = ttk.Combobox(form_frame, textvariable=sex_var, values=["Female", "Male", "Other/Not specified"], state="readonly")
        sex_combobox.grid(row=3, column=1, pady=5)
        def accept_participant():
            first_name = first_name_entry.get().strip()
            last_name = last_name_entry.get().strip()
            birth_date = birth_entry.get().strip()
            sex = sex_var.get()
            if not first_name or not last_name or not birth_date or sex == "Select":
                messagebox.showwarning("Warning", "Please fill in all fields correctly.")
                return
            try:
                import datetime
                datetime.datetime.strptime(birth_date, '%d/%m/%Y')
            except ValueError:
                messagebox.showwarning("Warning", "Invalid birth date format. Please use DD/MM/YYYY.")
                return
            participant_info = {
                "Type": "General",
                "First Name": first_name,
                "Last Name": last_name,
                "Birth Date": birth_date,
                "Sex": sex
            }
            if not self.is_duplicate_general(participant_info):
                self.save_participant_info(participant_info)
                messagebox.showinfo("Success", "Participant added successfully.")
                add_window.destroy()
            else:
                messagebox.showerror("Error", "Participant already exists.")
        accept_button = tk.Button(add_window, text="Accept", command=accept_participant,
                                  font=("Arial", 12, "bold"), bg="#4CAF50", fg="white")
        accept_button.pack(pady=20)

    def is_duplicate_general(self, participant_info):
        if os.path.exists(self.participants_file):
            with open(self.participants_file, 'r') as file:
                participants = json.load(file)
                for p in participants:
                    if (p["First Name"] == participant_info["First Name"] and
                        p["Last Name"] == participant_info["Last Name"] and
                        p["Birth Date"] == participant_info["Birth Date"] and
                        p["Sex"] == participant_info["Sex"]):
                        return True
        return False

    def save_participant_info(self, participant_info):
        if os.path.exists(self.participants_file):
            with open(self.participants_file, 'r') as file:
                participants = json.load(file)
        else:
            participants = []
        participants.append(participant_info)
        with open(self.participants_file, 'w') as file:
            json.dump(participants, file, indent=4)

    def view_participants(self):
        if not os.path.exists(self.participants_file):
            messagebox.showwarning("Warning", "No participants available.")
            return
        with open(self.participants_file, 'r') as file:
            participants = json.load(file)
        if not participants:
            messagebox.showwarning("Warning", "No participants available.")
            return
        participants_window = tk.Toplevel(self.root)
        participants_window.title("Participants List")
        participants_window.geometry("600x400")
        tree = ttk.Treeview(participants_window)
        tree['columns'] = ('First Name', 'Last Name', 'Birth Date', 'Sex')
        tree.column('#0', width=0, stretch=tk.NO)
        tree.column('First Name', anchor=tk.W, width=100)
        tree.column('Last Name', anchor=tk.W, width=100)
        tree.column('Birth Date', anchor=tk.CENTER, width=100)
        tree.column('Sex', anchor=tk.CENTER, width=100)
        tree.heading('#0', text='', anchor=tk.W)
        tree.heading('First Name', text='First Name', anchor=tk.W)
        tree.heading('Last Name', text='Last Name', anchor=tk.W)
        tree.heading('Birth Date', text='Birth Date', anchor=tk.CENTER)
        tree.heading('Sex', text='Sex', anchor=tk.CENTER)
        for participant in participants:
            tree.insert('', 'end', values=(
                participant['First Name'],
                participant['Last Name'],
                participant['Birth Date'],
                participant['Sex']
            ))
        tree.pack(pady=10, padx=10, fill='both', expand=True)

    def delete_participant(self):
        delete_window = tk.Toplevel(self.root)
        delete_window.title("Delete Participant")
        delete_window.geometry("600x400")
        delete_window.configure(bg="#E8F6F3")
        if not os.path.exists(self.participants_file):
            messagebox.showwarning("Warning", "No participants available.")
            return
        with open(self.participants_file, 'r') as file:
            participants = json.load(file)
        if not participants:
            messagebox.showwarning("Warning", "No participants available.")
            return
        tree = ttk.Treeview(delete_window, selectmode='browse')
        tree['columns'] = ('First Name', 'Last Name', 'Birth Date', 'Sex')
        tree.column('#0', width=0, stretch=tk.NO)
        tree.column('First Name', anchor=tk.W, width=100)
        tree.column('Last Name', anchor=tk.W, width=100)
        tree.column('Birth Date', anchor=tk.CENTER, width=100)
        tree.column('Sex', anchor=tk.CENTER, width=100)
        tree.heading('#0', text='', anchor=tk.W)
        tree.heading('First Name', text='First Name', anchor=tk.W)
        tree.heading('Last Name', text='Last Name', anchor=tk.W)
        tree.heading('Birth Date', text='Birth Date', anchor=tk.CENTER)
        tree.heading('Sex', text='Sex', anchor=tk.CENTER)
        for i, participant in enumerate(participants):
            tree.insert('', 'end', iid=i, values=(
                participant['First Name'],
                participant['Last Name'],
                participant['Birth Date'],
                participant['Sex']
            ))
        tree.pack(pady=10, padx=10, fill='both', expand=True)
        def confirm_delete():
            selected_item = tree.selection()
            if not selected_item:
                messagebox.showwarning("Warning", "Please select a participant to delete.")
                return
            participant_index = int(selected_item[0])
            participants.pop(participant_index)
            with open(self.participants_file, 'w') as file:
                json.dump(participants, file, indent=4)
            messagebox.showinfo("Success", "Participant deleted successfully.")
            delete_window.destroy()
        delete_button = tk.Button(delete_window, text="Delete Selected", command=confirm_delete,
                                  font=("Arial", 12, "bold"), bg="#f44336", fg="white")
        delete_button.pack(pady=20)

    # ---------------------------------------------------------------------------
    #                             CRONÓMETRO
    # ---------------------------------------------------------------------------
    def confirm_data(self):
        protocol = self.protocol_var.get()
        if not hasattr(self, 'participant_var') or protocol == "Select Protocol":
            messagebox.showwarning("Warning", "Please select a participant and a protocol.")
            return
        if self.is_duplicate(self.participant_var, protocol):
            messagebox.showerror("Error", f"The participant '{self.participant_var}' already has data for the protocol '{protocol}'.")
            return
        self.update_ui_for_confirmed_data()

    def update_ui_for_confirmed_data(self):
        self.start_button.config(state=tk.NORMAL)
        self.confirm_button.config(state=tk.DISABLED)
        self.cancel_button.config(state=tk.NORMAL)
        self.protocol_menu.config(state=tk.DISABLED)
        if self.protocol_var.get() == "HIGH":
            record = self.get_participant_record()
            if record and "HRrest" in record:
                self.hr_rest = record["HRrest"]
            if self.hr_rest is not None:
                age = self.calculate_age(record["Birth Date"])
                hrmax = 220 - age
                hrr = hrmax - self.hr_rest
                target_low = self.hr_rest + (hrr * 0.70)
                target_high = self.hr_rest + (hrr * 0.90)
                self.result_label.config(text=f"Resting HR: {self.hr_rest} bpm, Age: {age} years.\nTarget HR: {int(target_low)} - {int(target_high)} bpm")
            else:
                self.result_label.config(text="Please measure resting HR before starting HIGH protocol.")
        else:
            self.result_label.config(text="Press 'Start' to begin testing.")

    def get_participant_record(self):
        if not os.path.exists(self.participants_file):
            return None
        with open(self.participants_file, 'r') as file:
            participants = json.load(file)
        for p in participants:
            name = f"{p.get('First Name', '')} {p.get('Last Name', '')}"
            if name == self.participant_var:
                return p
        return None

    def calculate_age(self, birthdate_str):
        import datetime
        birth_date = datetime.datetime.strptime(birthdate_str, '%d/%m/%Y').date()
        today = datetime.date.today()
        age = today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))
        return age

    def is_duplicate(self, participant_id, protocol):
        if os.path.exists(self.filename):
            with open(self.filename, mode='r', newline='', encoding='utf-8') as file:
                reader = csv.reader(file, delimiter=';')
                next(reader)  # Saltamos cabecera
                for row in reader:
                    if row[0] == participant_id and row[1] == protocol:
                        return True
        return False

    def start_stopwatch(self):
        if self.protocol_var.get() == "HIGH":
            if self.hr_rest is None:
                messagebox.showwarning("Missing HRrest", "Please measure resting HR before starting the HIGH protocol.")
                return
        pygame.mixer.music.load(self.start_sound)
        pygame.mixer.music.play()
        self.start_time = time.perf_counter()
        self.running = True
        self.hr_readings = []
        self.update_ui_for_running_stopwatch()
        self.animate_gif()
        self.record_hr()

    def update_ui_for_running_stopwatch(self):
        self.result_label.config(text="Stopwatch running...")
        self.start_button.config(state=tk.DISABLED)
        self.cancel_button.config(state=tk.DISABLED)

    def record_hr(self):
        if self.running:
            current_hr = 0
            if self.hr_monitor:
                current_hr = self.hr_monitor.current_hr
            elapsed_time = time.perf_counter() - self.start_time
            self.hr_readings.append(current_hr)
            if self.hr_filename:
                with open(self.hr_filename, 'a', newline='', encoding='utf-8') as file:
                    writer = csv.writer(file, delimiter=';')
                    writer.writerow([
                        self.protocol_var.get(),
                        round(elapsed_time, 2),
                        current_hr
                    ])
            self.root.after(1000, self.record_hr)

    def animate_gif(self):
        if self.running and self.clock_gif_frames:
            self.current_frame_index = (self.current_frame_index + 1) % len(self.clock_gif_frames)
            self.clock_label.config(image=self.clock_gif_frames[self.current_frame_index])
            self.root.after(200, self.animate_gif)

    def stop_stopwatch(self, event):
        if self.running:
            end_time = time.perf_counter()
            elapsed_time = end_time - self.start_time
            self.running = False
            self.clock_label.configure(image=self.clock_image)
            self.collect_additional_data(elapsed_time)

    def collect_additional_data(self, elapsed_time):
        formatted_time = round(elapsed_time, 2)
        rpe = simpledialog.askinteger("RPE", "Enter RPE (6-20):", parent=self.root)
        mean_hr = round(sum(self.hr_readings) / len(self.hr_readings), 2) if self.hr_readings else 0
        self.save_record(formatted_time, rpe, mean_hr)
        self.reset_ui_after_test()

    def save_record(self, time_elapsed, rpe, mean_hr):
        with open(self.filename, 'a', newline='', encoding='utf-8') as file:
            writer = csv.writer(file, delimiter=';')
            writer.writerow([
                self.participant_var,
                self.protocol_var.get(),
                time_elapsed,
                rpe,
                mean_hr
            ])

    def reset_ui_after_test(self):
        self.protocol_menu.config(state=tk.NORMAL)
        self.select_participant_button.config(state=tk.NORMAL)
        self.confirm_button.config(state=tk.DISABLED)
        self.cancel_button.config(state=tk.DISABLED)
        self.result_label.config(text="Data saved. Ready for the next participant.")

    def cancel_test(self):
        self.protocol_menu.config(state=tk.NORMAL)
        self.select_participant_button.config(state=tk.NORMAL)
        self.confirm_button.config(state=tk.DISABLED)
        self.cancel_button.config(state=tk.DISABLED)
        self.start_button.config(state=tk.DISABLED)
        self.result_label.config(text="Test canceled. Ready for new input.")
        self.clock_label.configure(image=self.clock_image)
        self.running = False

    # ---------------------------------------------------------------------------
    #                           GESTIÓN DE DATOS
    # ---------------------------------------------------------------------------
    def view_data(self):
        if not os.path.exists(self.filename):
            messagebox.showwarning("Warning", "No data available.")
            return
        data_window = tk.Toplevel(self.root)
        data_window.title("Stored Data")
        data_window.geometry("600x400")
        tree = ttk.Treeview(data_window)
        tree['columns'] = ('Participant', 'Protocol', 'Time (seconds)', 'RPE', 'Mean HR')
        tree.column('#0', width=0, stretch=tk.NO)
        tree.column('Participant', anchor=tk.W, width=120)
        tree.column('Protocol', anchor=tk.W, width=120)
        tree.column('Time (seconds)', anchor=tk.CENTER, width=100)
        tree.column('RPE', anchor=tk.CENTER, width=80)
        tree.column('Mean HR', anchor=tk.CENTER, width=80)
        tree.heading('#0', text='', anchor=tk.W)
        tree.heading('Participant', text='Participant', anchor=tk.W)
        tree.heading('Protocol', text='Protocol', anchor=tk.W)
        tree.heading('Time (seconds)', text='Time (seconds)', anchor=tk.CENTER)
        tree.heading('RPE', text='RPE', anchor=tk.CENTER)
        tree.heading('Mean HR', text='Mean HR', anchor=tk.CENTER)
        with open(self.filename, mode='r', newline='', encoding='utf-8') as file:
            reader = csv.reader(file, delimiter=';')
            next(reader)
            for row in reader:
                tree.insert('', 'end', values=(row[0], row[1], row[2], row[3], row[4]))
        tree.pack(pady=10, padx=10, fill='both', expand=True)

    def delete_data_record(self):
        if not os.path.exists(self.filename):
            messagebox.showwarning("Warning", "No data available.")
            return
        delete_window = tk.Toplevel(self.root)
        delete_window.title("Delete Data Record")
        delete_window.geometry("600x400")
        tree = ttk.Treeview(delete_window, selectmode='browse')
        tree['columns'] = ('Participant', 'Protocol', 'Time (seconds)', 'RPE', 'Mean HR')
        tree.column('#0', width=0, stretch=tk.NO)
        tree.column('Participant', anchor=tk.W, width=120)
        tree.column('Protocol', anchor=tk.W, width=120)
        tree.column('Time (seconds)', anchor=tk.CENTER, width=100)
        tree.column('RPE', anchor=tk.CENTER, width=80)
        tree.column('Mean HR', anchor=tk.CENTER, width=80)
        tree.heading('#0', text='', anchor=tk.W)
        tree.heading('Participant', text='Participant', anchor=tk.W)
        tree.heading('Protocol', text='Protocol', anchor=tk.W)
        tree.heading('Time (seconds)', text='Time (seconds)', anchor=tk.CENTER)
        tree.heading('RPE', text='RPE', anchor=tk.CENTER)
        tree.heading('Mean HR', text='Mean HR', anchor=tk.CENTER)
        with open(self.filename, mode='r', newline='', encoding='utf-8') as file:
            all_rows = list(csv.reader(file, delimiter=';'))
            header = all_rows[0]
            data = all_rows[1:]
            for i, row in enumerate(data):
                tree.insert('', 'end', iid=i, values=(row[0], row[1], row[2], row[3], row[4]))
        tree.pack(pady=10, padx=10, fill='both', expand=True)
        def confirm_delete():
            selected_item = tree.selection()
            if not selected_item:
                messagebox.showwarning("Warning", "Please select a record to delete.")
                return
            record_index = int(selected_item[0])
            with open(self.filename, mode='r', newline='', encoding='utf-8') as file:
                all_rows = list(csv.reader(file, delimiter=';'))
            del all_rows[record_index + 1]
            with open(self.filename, mode='w', newline='', encoding='utf-8') as file:
                writer = csv.writer(file, delimiter=';')
                writer.writerows(all_rows)
            messagebox.showinfo("Success", "Record deleted successfully.")
            delete_window.destroy()
        delete_button = tk.Button(delete_window, text="Delete Selected", command=confirm_delete,
                                  font=("Arial", 12, "bold"), bg="#f44336", fg="white")
        delete_button.pack(pady=20)

    def export_to_excel(self):
        if not os.path.exists(self.filename):
            messagebox.showwarning("Warning", "No data available to export.")
            return
        df = pd.read_csv(self.filename, delimiter=';')
        excel_filename = self.filename.replace('.csv', '.xlsx')
        df.to_excel(excel_filename, index=False, engine='openpyxl')
        messagebox.showinfo("Export Successful", f"Data successfully exported to {excel_filename}")

    # ---------------------------------------------------------------------------
    #                ESCANEAR Y CONECTAR DISPOSITIVOS BLE
    # ---------------------------------------------------------------------------
    def scan_for_devices(self):
        self.scan_window = tk.Toplevel(self.root)
        self.scan_window.title("Scan for HR Devices")
        self.scan_window.geometry("400x300")
        self.scan_window.configure(bg="#E8F6F3")
        scan_label = tk.Label(self.scan_window, text="Scanning for devices...", font=("Arial", 12), bg="#E8F6F3")
        scan_label.pack(pady=10)
        def do_scan():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            devices = loop.run_until_complete(BleakScanner.discover(timeout=5.0))
            loop.close()
            self.root.after(0, lambda: self.show_scan_results(devices))
        threading.Thread(target=do_scan).start()

    def show_scan_results(self, devices):
        for widget in self.scan_window.winfo_children():
            widget.destroy()
        label = tk.Label(self.scan_window, text="Select a device:", font=("Arial", 12, "bold"), bg="#E8F6F3")
        label.pack(pady=10)
        listbox = tk.Listbox(self.scan_window, font=("Arial", 12), width=40, height=10)
        listbox.pack(pady=10)
        for device in devices:
            display_text = f"{device.name or 'Unknown'} ({device.address})"
            listbox.insert(tk.END, display_text)
        def select_device():
            selection = listbox.curselection()
            if not selection:
                messagebox.showwarning("Warning", "Please select a device.")
                return
            index = selection[0]
            selected_device = devices[index]
            if self.hr_monitor:
                self.hr_monitor.stop()
            self.hr_monitor = HeartRateMonitor(selected_device.address)
            self.hr_monitor.start()
            messagebox.showinfo("Device Selected", f"Connected to {selected_device.name} ({selected_device.address})")
            self.scan_window.destroy()
        select_button = tk.Button(self.scan_window, text="Select", command=select_device,
                                  font=("Arial", 12, "bold"), bg="#4CAF50", fg="white")
        select_button.pack(pady=10)

    # ---------------------------------------------------------------------------
    #        MÉTODO PARA ACTUALIZAR LA ETIQUETA DE HR EN TIEMPO REAL
    # ---------------------------------------------------------------------------
    def update_hr_label(self):
        if self.hr_monitor:
            hr_value = self.hr_monitor.current_hr
            self.hr_label.config(text=f"HR: {hr_value} bpm")
        else:
            self.hr_label.config(text="HR: -- bpm")
        self.root.after(1000, self.update_hr_label)

    # ---------------------------------------------------------------------------
    #                                SALIR
    # ---------------------------------------------------------------------------
    def confirm_exit(self):
        if messagebox.askyesno("Exit", "Are you sure you want to exit the application?"):
            if self.hr_monitor:
                self.hr_monitor.stop()
            self.root.quit()


if __name__ == "__main__":
    root = tk.Tk()
    app = StopwatchApp(root)
    root.mainloop()
