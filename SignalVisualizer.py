import math
import matplotlib.pyplot as plt
import numpy as np

# A script to visualize the sample(or time) versus magnitude signal from SDR tunned to 1090 MHz 
# WITH SDR Sampling Frequency set to 2 Million Sample Per Second

condition = True
while condition:

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
        
        def GetMagnitude(I,Q): 
            mag = math.sqrt(I*I + Q*Q) #calculate Magnitude 
            return round(mag, 2)
        
        
        for i in range(0,NSamples) : # To create two lists for I and Q samples and a list for Magnitudes

            if (i%2)==0 :
                I.append(chunk[i]-127.5)
                if i==2:
                        Magnitude.append(GetMagnitude(I[0],Q[0]))
                    
                elif i>3:
                    k = int((i/2)-1)
                    Magnitude.append(GetMagnitude(I[k],Q[k]))
            else:
                Q.append(chunk[i]-127.5)
            

        
    # preamble pulses
    print(len(Magnitude))
    preamble = np.zeros(16) #To create a list of 16 items that are zeros 
    preamble[1],preamble[5],preamble[8],preamble[10]= np.zeros(4)-1 # Adding wheights to try to get better correlation
    preamble[0],preamble[2],preamble[7],preamble[9]= np.zeros(4)+1 # Our preamble has a pulse at 0,1,3.5,4.5 micro sec
    
    Corrlation = []
    limit = int(NSamples/2)
    print(limit)
    for To in range(0, limit-17): #Cross correlation
        temp=0
        k=0
        for j in range(0,16):
            temp= temp+k
            
            k = Magnitude[To+j]*preamble[j]
        Corrlation.append(temp)
    for v in range(0, len(Corrlation)):
        if Corrlation[v] > 0:

            print(f"\n The shift is <<{v}>> and The Corrlation is <<{Corrlation[v]}>>")

    #Plotting the data using Matplotlib
    
    plt.style.use('_mpl-gallery')


    # make data
    Samples = int(NSamples/2)-1
    x = np.arange(0, int(Samples))
    y = Magnitude

    # plot
    fig = plt.figure(figsize=(6, 4))
    ax = fig.add_axes([0.07, 0.1, 1, 1])
    #fig, ax = plt.subplots(figsize=(4, 2))

    ax.plot(x, y)
    ax.set_xlabel(f"IQ SAMPLES (A sample in 0.5 micro sec) S:{int(start_byte/2)}")
    ax.set_ylabel("Magnitude ")

    ax.set(xlim=(0,Samples), xticks=scaler*np.arange(1, Samples/scaler),
           ylim=(0, 5), yticks=np.arange(1, 5))
    plt.grid(visible=True)
    plt.show()

    



     
