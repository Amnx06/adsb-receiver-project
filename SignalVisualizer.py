import math
import matplotlib.pyplot as plt
import numpy as np
import time
from matplotlib.widgets import Button,TextBox
import threading 

# A script to visualize the sample(or time) versus magnitude signal from SDR tunned to 1090 MHz 
# WITH SDR Sampling Frequency set to 2 Million Sample Per Second

condition = True
while condition:
    s=0
    print("=====================>>>>>>>><<<<<<<==================")
    print("\nWelcome to ADS-B Visualizer >>>")
    print("\nPress 0 to exit ")
    
    NSamples = int(input("Enter the number of samples in plot : 20,100,2000 :"))*2
    timeOfPlot = (NSamples/2)*0.5
    SliceN = input(f"Select the slice you want to visulaulize by entering the X multiple integer of the {timeOfPlot} micro sec: ")

    if int(SliceN)==0:
        break
    if NSamples<= 50:
        scaler=1
    elif NSamples> 50 and NSamples<200:
        scaler=2
    elif NSamples>= 200 and NSamples<1000:
        scaler=50
    else:
        scaler = 100
        
    BinaryFile = "captures/capture_Stah1090MHZ.bin"

    start_byte = 0# Where to start reading
    

    with open(BinaryFile, "rb") as f:
        #  Move the pointer to the start of your slice
        start_byte= (NSamples)*(int(SliceN)-1)
        f.seek(start_byte)
        		 	
        chunk = f.read(NSamples)
        I = []
        Q = []
        Magnitude = []
        DC_Shift = 0.7
        def GetMagnitude(I,Q): 
            mag = math.sqrt(I*I + Q*Q) #calculate Magnitude 
            return round(mag, 2)
        
        
        for i in range(0,NSamples) : # To create two lists for I and Q samples and a list for Magnitudes

            if (i%2)==0 :
                I.append(chunk[i]-127.5)
                if i==2:
                        Magnitude.append(GetMagnitude(I[0],Q[0])- DC_Shift)
                    
                elif i>3:
                    k = int((i/2)-1)
                    Magnitude.append(GetMagnitude(I[k],Q[k])- DC_Shift)
            else:
                Q.append(chunk[i]-127.5)
            

        
    # preamble pulses
    #print(len(Magnitude))
    preamble = np.zeros(16) #To create a list of 16 items that are zeros 
    PeaksIndex = [0,2,7,9]
    #print(preamble)
    
    f = []
    for r in range(0,16):
        for indx in PeaksIndex :
            
            
            a = r==int(indx)
            f.append(a)
            if len(f)==len(PeaksIndex):
                if sum(f)==1:
                    preamble[r]=1
                    f=[]
                else:
                    
                    preamble[r] = -1
                    f=[] # to write preamble pulses 
                

                

    #print(preamble)
    Pcounter=0
    PreambleStart = []
    limit = int(NSamples/2)-17
    #EstimtedTime = (limit/10000)*37
    #print(f"Time Estimation is {EstimtedTime} in Second")

    lock = threading.Lock() # used to enable multiple threads to print or append list without corrupting the data
    Pcounter=0
    PreambleStart = []
    
    def PreambleDetector(preamble,peaksIndex, G, StartT,FinishT, ThreadNum): #G is the multiple that we want to compare to the noise  
        global Pcounter, PreambleStart
        peaks = []
        vallies = []
        
        preD=[]
        
        WeightedSamples =[]
        for To in range(StartT, FinishT): #creating weighted samples, expected pulses index*1(peaks)
                
            m=0   # other index vallies and multiplied by -1
            for j in range(0,16):
                    
                m = Magnitude[To+j]*preamble[j]
                WeightedSamples.append(m)
                for index in peaksIndex:
                    e= j == int(index)
                    preD.append(e)
                    if len(preD) == len(peaksIndex):
                        if sum(preD)==1:
                            peaks.append(WeightedSamples[j])
                            preD=[]
                        else:
                            vallies.append(m)
                            preD=[]

            ValliesAvg = -(sum(vallies)/len(vallies))
            ValliesMax = -min(vallies)*2
            PeakMin = min(peaks)
            
            p = PeakMin-G*ValliesAvg
            
            
            with lock:
                if (PeakMin>5*ValliesAvg) and (PeakMin>0.6) :
                    if PeakMin > ValliesMax:
                    
                    # here use thread 
                        PreambleStart.append(To)
                        #print(f"\nvallies max {ValliesMax} and PeakMin {PeakMin}, ")
                        Pcounter = Pcounter+1

            WeightedSamples = []
            peaks = []
            vallies =[]

    level = int(limit/4)

    thread1 = threading.Thread(target = PreambleDetector, args= (preamble,PeaksIndex,2,0,level, 1))

    thread2 = threading.Thread(target = PreambleDetector, args= (preamble,PeaksIndex,2,level,2*level,2))

    thread3 = threading.Thread(target = PreambleDetector, args= (preamble,PeaksIndex,2,2*level,level*3,3))

    thread4 = threading.Thread(target = PreambleDetector, args= (preamble,PeaksIndex,2,3*level,4*level,4))
    
    thread1.start()
    
    thread2.start()

    thread3.start()
    
    thread4.start()
    
    thread1.join()#The Main Thread "hangs" right there. It will not execute the next line until the thread being "joined" is done
    
    thread2.join()
    
    thread3.join()
    
    thread4.join()
    
    print(f"\n >>>>>Total Preamble detected {Pcounter} at {PreambleStart}  shifts<<<<<<")

    msg ={}
    for start in PreambleStart:
            msg[start]= Magnitude[start + 16:start+ 240]
    #print(msg)

    def Bit_Slicer(message):
        
        for key,value in message.items():
            print(f"key is {key}")
            decoded=[]
            for k in range(0,223,2):
                if value[k] > value[k+1]:
                    decoded.append(1) 
                elif value[k] < value[k+1]:
                    decoded.append(0)
                else:
                    #del message[key]
                    print(f"Value 1 :{value[k]} and value2 : {value[k+1]} ")
                    decoded[:] = "Rejected"
                    break
            print(len(decoded))
            message[key]="".join(map(str,decoded))
            print()
    #Plotting the data using Matplotlib
    
    Bit_Slicer(msg)
    print(msg)
    if limit < 2000:
        plt.style.use('_mpl-gallery')
        
        class SignalShifter:
            def __init__(self, stem_container, base_xx, base_yy):
                self.shift_amount = 0
                self.stem_container = stem_container
                self.base_xx = base_xx
                self.base_yy = base_yy
            def Update_position(self):
                #new X positions
                new_xx = self.base_xx + self.shift_amount
                
                #Update the stem markers (the dots)
                self.stem_container.markerline.set_xdata(new_xx)#the circle at the top of the stick
                
                #Update the stem lines (the vertical sticks)
                new_segments = [[[x, 0], [x, y]] for x, y in zip(new_xx, self.base_yy)] #[[x, 0], [x, y]] this represnet the coordinate 
                self.stem_container.stemlines.set_segments(new_segments)#of the starting and ending point of the vertical line stick
                #zip takes your new x positions and your original heights (y) and pairs them up like a zipper. 
                #If x=5 and y=0.5, they become a pair: (5, 0.5).
                
                # 5. Redraw the plot!
                plt.draw()

            def Shift_by_button(self, event):
                
                self.shift_amount += 1
                self.Update_position()
                #print(f"Shift amount: {self.shift_amount}")
                
                
            def Shift_by_TextBox(self, text):
                try:
                    self.shift_amount=int(text)
                    self.Update_position()
                except:
                    print("enter an integer")


        Samples = int(NSamples/2)-1
        x = np.arange(0, int(Samples))
        y = Magnitude

        # the preamble pattern 
        xx = np.arange(0, 16)
        yy = np.zeros(16)
        yy[0], yy[2], yy[7], yy[9] = 0.5, 0.5, 0.5, 0.5

        
        fig = plt.figure(figsize=(6, 4))
        ax = fig.add_axes([0.07, 0.1, 1, 1])

        # Plot signal and stem
        ax.plot(x, y, label="Signal")
        line = ax.stem(xx, yy, linefmt='red', label="Preamble pulses")

        ax.set_xlabel(f"IQ SAMPLES (A sample in 0.5 micro sec) S:{int(start_byte/2)}")
        ax.set_ylabel("Magnitude ")

        ax.set(xlim=(0, Samples), xticks= scaler*np.arange(1, Samples/scaler),
               ylim=(0, 12), yticks=np.arange(1, 12))

        #  Button
        # Pass the stem container (line) and base arrays into the class
        callback = SignalShifter(line, xx, yy)

        ax_button = plt.axes([0.04, 0.005, 0.1, 0.04]) # [left, bottom, width, height]
        btn = Button(ax_button, 'Shift', color='lightgray', hovercolor='white')
        btn.on_clicked(callback.Shift_by_button)
        box = plt.axes([0.87, 0.005, 0.1, 0.04])
        InputShift= TextBox(box, "jump to: ", initial = "0")
        InputShift.on_submit(callback.Shift_by_TextBox)
        plt.grid(visible=True)
        plt.show()


    else :
        print("\n Reduce the number of Samples in plot -must be lower than 2000 - in order to VISUALIZE!")