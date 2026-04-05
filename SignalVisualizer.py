import math
import matplotlib.pyplot as plt
import numpy as np
import time
from matplotlib.widgets import Button,TextBox

# A script to visualize the sample(or time) versus magnitude signal from SDR tunned to 1090 MHz 
# WITH SDR Sampling Frequency set to 2 Million Sample Per Second

condition = True
while condition:
    s=0
    print("Welcome to ADS-B Visualizer >>>")
    print("Each plot represent 0.5 ms: press 0 to exit ")
    
    NSamples = int(input("Enter the number of samples in plot : 20,100,2000 :"))*2
    timeOfPlot = (NSamples/2)*0.5
    SliceN = input(f"Select the slice you want to visulaulize by entering the X multiple integer of the {timeOfPlot} micro sec: ")

    if int(SliceN)==0:
        break
    if NSamples<= 50:
        scaler=1
    elif NSamples> 50 and NSamples<200:
        scaler=2
    elif NSamples>= 200:
        scaler=50
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
                    preamble[r]=3
                    f=[]
                else:
                    #print(f"r > {r}  index {indx}")
                    preamble[r] = -1
                    f=[]
                

                

    #print(preamble)
    Pcounter=0
    PreambleStart = []
    limit = int(NSamples/2)
    EstimtedTime = (limit/10000)*37
    print(f"Time Estimation is {EstimtedTime} in Second")
    def PreambleDetector(preamble,peaksIndex, G): #G is the multiple that we want to campare to the noise  
        Pcounter=0
        peaks = []
        PreambleStart = []
        preD=[]
        vallies = []
        WeightedSamples =[]
        for To in range(0, limit-17): #Cross correlation
            PercentageFinish = 100*(To)/(limit-17)
            PercentageFinish= round(PercentageFinish, 2)
            if PercentageFinish % 10== 0:
                
                print(f"\nProgress >> {PercentageFinish} %")
            m=0
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
            #print(len(peaks))
            #print(len(vallies))
            PeakMin = min(peaks)
            #print(f"\n vallies >> {vallies} and Peakmin> {peaks}< at shift >{To}<")
            
            #print(f"\n vallies avg >> {ValliesAvg} and Peakmin> {PeakMin}< at shift >{To}<")
            p = PeakMin-G*ValliesAvg
            #print(f"\n diff >> {p} at shift > {To}<")
            if (PeakMin>G*ValliesAvg):
                PreambleStart.append(To)
                print(f"Possible Preamble AT shift <{To}>")
                Pcounter = Pcounter+1
            peaks = []
            vallies =[]
        print(f"Total Preamble detected {Pcounter} at {PreambleStart}  shifts")
    PreambleDetector(preamble,PeaksIndex,2)
    #Plotting the data using Matplotlib
    
    plt.style.use('_mpl-gallery')
    #class SignalShifter:
    #def __init__(self, line_obj, x_data, y_data):
       # self.line = line_obj
      #  self.x_original = x_data
     #   self.y_original = y_data
    #    self.shift_amount = 0  # This is the variable you want to access

   # def shift_right(self, event):
        # 1. Increment the internal state
    #    self.shift_amount += 1
        
        # 2. Add the shift to the X data
        #new_x = self.x_original + self.shift_amount
        
        # 3. Update the plot object with the NEW data
        #self.line.set_xdata(new_x)
        
        # 4. Redraw
       # plt.draw()
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

    ax.set(xlim=(0, Samples), xticks=scaler*np.arange(1, Samples/scaler),
           ylim=(0, 5), yticks=np.arange(1, 5))

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